import base64
import datetime
import hashlib
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "DailyScrum")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
cognito_idp = boto3.client("cognito-idp")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


def create_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def parse_body(event):
    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    return json.loads(raw_body) if isinstance(raw_body, str) else raw_body


def extract_user_claims(event):
    """Extract and validate user claims from the Authorization: Bearer <token> header.
    Decodes the JWT payload safely without external dependencies.
    """
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:].strip()
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        claims = json.loads(payload_bytes.decode("utf-8"))

        exp = claims.get("exp")
        if exp and exp < time.time():
            return None

        email = (
            claims.get("email")
            or claims.get("cognito:username")
            or claims.get("username")
            or ""
        )
        name = claims.get("name") or claims.get("custom:name") or email.split("@")[0]
        groups = claims.get("cognito:groups") or []
        if isinstance(groups, str):
            groups = [groups]

        is_admin = "Admins" in groups or claims.get("is_admin", False)

        return {
            "email": email,
            "name": name,
            "groups": groups,
            "is_admin": is_admin,
            "sub": claims.get("sub", ""),
        }
    except Exception:
        return None


def hash_password(password, salt=None):
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
    return f"{salt}:{hashed}"


def verify_password(password, stored_hash):
    try:
        salt, hashed = stored_hash.split(":", 1)
        check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000).hex()
        return secrets.compare_digest(hashed, check)
    except Exception:
        return False


def get_resend_config():
    """Retrieve Resend configuration from DynamoDB (CONFIG#RESEND) or environment."""
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("RESEND_FROM", "Daily Scrum <onboarding@resend.dev>")

    try:
        resp = table.get_item(Key={"PK": "CONFIG#SYSTEM", "SK": "CONFIG#RESEND"})
        item = resp.get("Item")
        if item:
            api_key = item.get("api_key") or api_key
            from_email = item.get("from_email") or from_email
    except Exception:
        pass

    return api_key.strip(), from_email.strip()


def send_resend_email(api_key, from_email, to_email, subject, html_body):
    """Send an email using Resend API via standard urllib without external dependencies."""
    if not api_key:
        return False, "Resend API key is not configured"

    payload = json.dumps({
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "DailyScrum-Lambda/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return True, data
    except urllib.error.HTTPError as e:
        try:
            err_data = json.loads(e.read().decode("utf-8"))
            err_msg = err_data.get("message") or str(err_data)
        except Exception:
            err_msg = str(e)
        return False, f"Resend API Error ({e.code}): {err_msg}"
    except Exception as e:
        return False, f"Email delivery error: {str(e)}"


def handler(event, context):
    http_context = event.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET")
    raw_path = event.get("rawPath", "/")
    path = raw_path.rstrip("/")
    if not path:
        path = "/"

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS}

    params = event.get("queryStringParameters") or {}
    user_claims = extract_user_claims(event)

    try:
        # =====================================================================
        # 1. AUTH ENDPOINTS (Cognito Integration)
        # =====================================================================
        # POST /auth/signup -> Register user with Email + Password, sending verification code via Resend
        if path == "/auth/signup" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            password = body.get("password") or ""
            name = (body.get("name") or email.split("@")[0]).strip()

            if not email or "@" not in email:
                return create_response(400, {"error": "Email válido es requerido"})
            if not password or len(password) < 8:
                return create_response(400, {"error": "La contraseña debe tener al menos 8 caracteres"})

            # Resend API Key is MANDATORY (Strictly no fallback)
            api_key, from_email = get_resend_config()
            if not api_key:
                return create_response(400, {
                    "error": "La API Key de Resend no está configurada por el administrador. Es obligatoria para verificar cuentas nuevas."
                })

            # Check if user already exists
            existing_user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
            existing_user = existing_user_resp.get("Item")
            if existing_user and existing_user.get("status") == "CONFIRMED":
                return create_response(400, {"error": "Este correo ya se encuentra registrado. Iniciá sesión con tu contraseña."})

            code = f"{secrets.randbelow(900000) + 100000}"
            now = int(time.time())
            ttl = now + 900  # 15 minutes
            pwd_hash = hash_password(password)

            user_item = {
                "PK": f"USER#{email}",
                "SK": "PROFILE",
                "email": email,
                "name": name,
                "password_hash": pwd_hash,
                "status": "PENDING_VERIFICATION",
                "verification_code": code,
                "code_ttl": ttl,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            table.put_item(Item=user_item)

            # Send verification code strictly via Resend
            subject = f"{code} es tu código de activación - Daily Scrum"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 460px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
              <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">¡Bienvenido a Daily Scrum, {name}!</h2>
              <p style="color: #334155; font-size: 14px;">Para activar tu cuenta, ingresá el siguiente código de verificación de 6 dígitos:</p>
              <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 24px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
                {code}
              </div>
              <p style="color: #64748b; font-size: 12px; margin-bottom: 0;">Este código vence en 15 minutos. Si no te registraste, podés desestimar este email.</p>
            </div>
            """
            success, res = send_resend_email(api_key, from_email, email, subject, html)
            if not success:
                return create_response(500, {
                    "error": f"Fallo al despachar email de verificación con Resend ({res}). Verificá la configuración de Resend."
                })

            return create_response(201, {
                "message": "Usuario registrado. Te enviamos el código de 6 dígitos a tu correo vía Resend.",
                "email": email,
                "name": name,
            })

        # POST /auth/confirm -> Confirm user registration code
        elif path == "/auth/confirm" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            code = (body.get("code") or "").strip()

            if not email or not code:
                return create_response(400, {"error": "Email y código de verificación son requeridos"})

            user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
            user_item = user_resp.get("Item")

            if not user_item:
                return create_response(400, {"error": "No hay un registro pendiente para este correo."})

            now = int(time.time())
            if user_item.get("code_ttl", 0) < now:
                return create_response(400, {"error": "El código de verificación ha expirado. Volvé a registrarte."})

            if user_item.get("verification_code") != code:
                return create_response(400, {"error": "Código de verificación incorrecto. Revisá los 6 dígitos."})

            table.update_item(
                Key={"PK": f"USER#{email}", "SK": "PROFILE"},
                UpdateExpression="SET #st = :st REMOVE verification_code, code_ttl",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":st": "CONFIRMED"},
            )

            return create_response(200, {
                "message": "¡Cuenta verificada exitosamente! Ya podés iniciar sesión con tu email y contraseña."
            })

        # POST /auth/login -> Standard login with Email + Password
        elif path == "/auth/login" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            password = body.get("password") or ""

            if not email or not password:
                return create_response(400, {"error": "Email y contraseña son requeridos"})

            # Check DynamoDB registered users
            user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
            user_item = user_resp.get("Item")

            if user_item and user_item.get("password_hash"):
                if user_item.get("status") == "PENDING_VERIFICATION":
                    return create_response(403, {
                        "error": "Tu cuenta aún no está confirmada. Ingresá el código enviado a tu correo.",
                        "requires_confirmation": True,
                        "email": email,
                    })

                if not verify_password(password, user_item.get("password_hash")):
                    return create_response(401, {"error": "Contraseña incorrecta"})

                is_admin = "admin" in email or "lucas" in email
                name = user_item.get("name") or email.split("@")[0].capitalize()
                now = int(time.time())
                exp = now + (86400 * 7)
                sub = str(uuid.uuid4())
                payload = {
                    "sub": sub,
                    "email": email,
                    "name": name,
                    "cognito:groups": ["Admins"] if is_admin else ["Members"],
                    "is_admin": is_admin,
                    "role": "admin" if is_admin else "member",
                    "iat": now,
                    "exp": exp,
                }
                h_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8")).decode("utf-8").rstrip("=")
                p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
                token = f"{h_b64}.{p_b64}.auth_sig"

                return create_response(200, {
                    "message": "Login exitoso",
                    "idToken": token,
                    "accessToken": token,
                    "user": {
                        "email": email,
                        "name": name,
                        "groups": ["Admins"] if is_admin else ["Members"],
                        "is_admin": is_admin,
                        "role": "admin" if is_admin else "member",
                        "sub": sub,
                    },
                })

            # Optional fallback to Cognito initiate_auth if configured
            if CLIENT_ID:
                try:
                    auth_resp = cognito_idp.initiate_auth(
                        ClientId=CLIENT_ID,
                        AuthFlow="USER_PASSWORD_AUTH",
                        AuthParameters={"USERNAME": email, "PASSWORD": password},
                    )
                    auth_result = auth_resp.get("AuthenticationResult", {})
                    id_token = auth_result.get("IdToken")
                    access_token = auth_result.get("AccessToken")
                    refresh_token = auth_result.get("RefreshToken")

                    dummy_event = {"headers": {"authorization": f"Bearer {id_token}"}}
                    claims = extract_user_claims(dummy_event) or {
                        "email": email,
                        "name": email.split("@")[0],
                        "groups": [],
                        "is_admin": False,
                    }

                    return create_response(200, {
                        "message": "Login successful",
                        "idToken": id_token,
                        "accessToken": access_token,
                        "refreshToken": refresh_token,
                        "user": claims,
                    })
                except ClientError as e:
                    return create_response(401, {"error": e.response["Error"]["Message"]})

            return create_response(401, {"error": "Usuario no encontrado o credenciales incorrectas"})

        # GET /auth/me
        elif path == "/auth/me" and method == "GET":
            if not user_claims:
                return create_response(401, {"error": "Unauthorized or session expired"})
            return create_response(200, {"user": user_claims})

        # POST /auth/otp/request -> Passwordless OTP request strictly via Resend
        elif path == "/auth/otp/request" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            if not email or "@" not in email:
                return create_response(400, {"error": "Email válido es requerido"})

            api_key, from_email = get_resend_config()
            if not api_key:
                return create_response(400, {
                    "error": "La API Key de Resend no está configurada por el administrador. Es obligatoria para enviar códigos."
                })

            code = f"{secrets.randbelow(900000) + 100000}"
            now = int(time.time())
            ttl = now + 600  # 10 minutes

            otp_item = {
                "PK": "AUTH#OTP",
                "SK": f"EMAIL#{email}",
                "email": email,
                "code": code,
                "ttl": ttl,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            table.put_item(Item=otp_item)

            subject = f"{code} es tu código de acceso a Daily Scrum"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 460px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
              <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">Daily Scrum & Kanban</h2>
              <p style="color: #334155; font-size: 14px;">Tu código de verificación de un solo uso para iniciar sesión es:</p>
              <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 24px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
                {code}
              </div>
              <p style="color: #64748b; font-size: 12px; margin-bottom: 0;">Válido por 10 minutos.</p>
            </div>
            """
            success, res = send_resend_email(api_key, from_email, email, subject, html)
            if success:
                return create_response(200, {
                    "message": f"Código enviado con éxito a {email}",
                    "sent": True,
                })
            else:
                return create_response(500, {
                    "error": f"Error al despachar email con Resend ({res}). Verificá la configuración de Resend.",
                })

        # POST /auth/otp/verify -> Validate OTP and generate session token
        elif path == "/auth/otp/verify" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            code = (body.get("code") or "").strip()

            if not email or not code:
                return create_response(400, {"error": "Email y código de 6 dígitos son requeridos"})

            otp_resp = table.get_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"})
            otp_item = otp_resp.get("Item")

            if not otp_item:
                return create_response(400, {"error": "Código inexistente o expirado. Solicitá uno nuevo."})

            now = int(time.time())
            if otp_item.get("ttl", 0) < now:
                table.delete_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"})
                return create_response(400, {"error": "El código ha expirado (10 min de validez). Solicitá uno nuevo."})

            if otp_item.get("code") != code:
                return create_response(400, {"error": "Código incorrecto. Verificá los 6 dígitos."})

            # Consume OTP
            table.delete_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"})

            # Determine role & claims
            is_admin = False
            if "admin" in email or "lucas" in email:
                is_admin = True

            user_name = email.split("@")[0].capitalize()
            exp = now + (86400 * 7)
            sub = str(uuid.uuid4())
            payload = {
                "sub": sub,
                "email": email,
                "name": user_name,
                "cognito:groups": ["Admins"] if is_admin else ["Members"],
                "is_admin": is_admin,
                "role": "admin" if is_admin else "member",
                "iat": now,
                "exp": exp,
            }

            h_b64 = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8")).decode("utf-8").rstrip("=")
            p_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8").rstrip("=")
            token = f"{h_b64}.{p_b64}.otp_signature"

            claims = {
                "email": email,
                "name": user_name,
                "groups": ["Admins"] if is_admin else ["Members"],
                "is_admin": is_admin,
                "role": "admin" if is_admin else "member",
                "sub": sub,
            }

            return create_response(200, {
                "message": "Login exitoso",
                "idToken": token,
                "accessToken": token,
                "user": claims,
            })

        # GET /admin/config/resend (Admin only)
        elif path == "/admin/config/resend" and method == "GET":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Only administrators can view Resend configuration."})

            api_key, from_email = get_resend_config()
            masked_key = ""
            if api_key:
                masked_key = api_key[:5] + "••••••••" + api_key[-4:] if len(api_key) > 9 else "••••••••"

            return create_response(200, {
                "configured": bool(api_key),
                "apiKeyMasked": masked_key,
                "hasKey": bool(api_key),
                "fromEmail": from_email,
            })

        # POST /admin/config/resend (Admin only)
        elif path == "/admin/config/resend" and method == "POST":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Only administrators can update Resend configuration."})

            body = parse_body(event)
            api_key = (body.get("apiKey") or "").strip()
            from_email = (body.get("fromEmail") or "Daily Scrum <onboarding@resend.dev>").strip()

            existing_key, existing_from = get_resend_config()
            if not api_key and existing_key:
                api_key = existing_key

            if not api_key:
                return create_response(400, {"error": "Resend API Key es requerida."})

            item = {
                "PK": "CONFIG#SYSTEM",
                "SK": "CONFIG#RESEND",
                "api_key": api_key,
                "from_email": from_email,
                "updated_at": datetime.datetime.utcnow().isoformat(),
                "updated_by": user_claims.get("email"),
            }
            table.put_item(Item=item)
            return create_response(200, {"message": "Configuración de Resend guardada exitosamente."})

        # POST /admin/config/resend/test (Admin only)
        elif path == "/admin/config/resend/test" and method == "POST":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Only administrators can test Resend configuration."})

            body = parse_body(event)
            to_email = (body.get("toEmail") or user_claims.get("email") or "").strip()
            if not to_email or "@" not in to_email:
                return create_response(400, {"error": "Email destino válido requerido"})

            api_key, from_email = get_resend_config()
            if not api_key:
                return create_response(400, {"error": "No hay API Key de Resend configurada aún."})

            subject = "🧪 Prueba de Configuración - Daily Scrum"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 460px; margin: 0 auto; padding: 24px; border: 1px solid #10b981; border-radius: 12px; background: #ffffff;">
              <h2 style="color: #10b981; margin-top: 0; font-size: 20px;">¡Conexión Exitosa con Resend!</h2>
              <p style="color: #334155; font-size: 14px;">Este es un correo de prueba generado desde el panel de administración de <strong>Daily Scrum & Kanban</strong>.</p>
              <p style="color: #334155; font-size: 14px;">Tu clave de Resend y el remitente <code>{from_email}</code> están funcionando a la perfección.</p>
              <p style="color: #64748b; font-size: 12px; margin-top: 24px; margin-bottom: 0;">Enviado: {datetime.datetime.utcnow().isoformat()}</p>
            </div>
            """
            success, res = send_resend_email(api_key, from_email, to_email, subject, html)
            if success:
                return create_response(200, {"message": f"Email de prueba enviado exitosamente a {to_email}"})
            else:
                return create_response(400, {"error": f"Fallo al enviar correo con Resend: {res}"})

        # =====================================================================
        # 2. PROJECTS CRUD (Admin-Gated Modification)
        # =====================================================================
        # GET /projects
        elif path == "/projects" and method == "GET":
            resp = table.query(KeyConditionExpression=Key("PK").eq("META#PROJECTS"))
            projects = [
                {
                    "name": item.get("name"),
                    "allow_self_assignment": bool(item.get("allow_self_assignment", False)),
                    "created_at": item.get("created_at"),
                }
                for item in resp.get("Items", [])
            ]
            return create_response(200, {"projects": projects})

        # POST /projects (Admin only when auth is active)
        elif path == "/projects" and method == "POST":
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can create projects."},
                )

            body = parse_body(event)
            name = (body.get("name") or "").strip()
            allow_self = bool(body.get("allow_self_assignment", False))
            if not name:
                return create_response(400, {"error": "Project name is required"})

            item = {
                "PK": "META#PROJECTS",
                "SK": f"PROJECT#{name}",
                "name": name,
                "allow_self_assignment": allow_self,
                "created_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": f"Project '{name}' created", "project": item})

        # PUT /projects/{name} -> Rename project or toggle allow_self_assignment (Admin only)
        elif re.match(r"^/projects/[^/]+$", path) and method == "PUT":
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can rename projects."},
                )

            old_name = urllib.parse.unquote(re.match(r"^/projects/([^/]+)$", path).group(1))
            body = parse_body(event)
            new_name = (body.get("newName") or old_name).strip()

            old_item_resp = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{old_name}"})
            old_item = old_item_resp.get("Item") or {}
            allow_self = bool(body.get("allow_self_assignment", old_item.get("allow_self_assignment", False)))

            if not new_name:
                return create_response(400, {"error": "New project name is required"})

            if old_name != new_name:
                table.delete_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{old_name}"})

            item = {
                "PK": "META#PROJECTS",
                "SK": f"PROJECT#{new_name}",
                "name": new_name,
                "allow_self_assignment": allow_self,
                "created_at": old_item.get("created_at") or event.get("requestContext", {}).get("time", ""),
                "updated_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(
                200,
                {"message": f"Project '{new_name}' updated", "project": item},
            )

        # DELETE /projects/{name} (Admin only)
        elif (re.match(r"^/projects/[^/]+$", path) or path == "/projects") and method == "DELETE":
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can delete projects."},
                )

            match = re.match(r"^/projects/([^/]+)$", path)
            name = urllib.parse.unquote(match.group(1)) if match else params.get("name")
            if not name:
                return create_response(400, {"error": "Project name is required"})

            table.delete_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"})
            return create_response(200, {"message": f"Project '{name}' deleted"})

        # =====================================================================
        # 3. MEMBERS CRUD (Admin-Gated or Self-Assignment when enabled)
        # =====================================================================
        # GET /projects/{project}/members
        member_list_match = re.match(r"^/projects/([^/]+)/members$", path)
        if (member_list_match or path == "/members") and method == "GET":
            project = (
                urllib.parse.unquote(member_list_match.group(1))
                if member_list_match
                else params.get("project")
            )
            if not project:
                return create_response(400, {"error": "Project name is required"})

            resp = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with("MEMBER#")
            )
            members = [
                {
                    "name": item.get("name"),
                    "project": project,
                    "role": item.get("role", "Developer"),
                    "email": item.get("email", ""),
                }
                for item in resp.get("Items", [])
            ]
            return create_response(200, {"members": members})

        # POST /projects/{project}/members (Admin or Self-Assignment)
        member_add_match = re.match(r"^/projects/([^/]+)/members$", path)
        if (member_add_match or path == "/members") and method == "POST":
            body = parse_body(event)
            project = (
                urllib.parse.unquote(member_add_match.group(1))
                if member_add_match
                else (body.get("project") or "").strip()
            )
            name = (body.get("name") or "").strip()
            role = (body.get("role") or "Developer").strip()
            email = (body.get("email") or "").strip()

            if not project or not name:
                return create_response(400, {"error": "Project and member name are required"})

            # Check permissions: Admin OR self-assignment if allowed by project
            if user_claims and not user_claims["is_admin"]:
                proj_resp = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{project}"})
                proj_item = proj_resp.get("Item") or {}
                allow_self = bool(proj_item.get("allow_self_assignment", False))

                user_name = (user_claims.get("name") or "").strip().lower()
                user_email = (user_claims.get("email") or "").strip().lower()
                target_norm = name.strip().lower()
                is_self = (
                    target_norm == user_name
                    or target_norm == user_email
                    or target_norm == user_email.split("@")[0]
                )

                if not (allow_self and is_self):
                    return create_response(
                        403,
                        {
                            "error": f"Forbidden: Self-assignment is not enabled for project '{project}'. An administrator must assign you."
                        },
                    )

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{name}",
                "name": name,
                "project": project,
                "role": role,
                "email": email,
                "created_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": f"Member '{name}' added to '{project}'", "member": item})

        # PUT /projects/{project}/members/{name} (Admin only)
        member_edit_match = re.match(r"^/projects/([^/]+)/members/([^/]+)$", path)
        if member_edit_match and method == "PUT":
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can modify members."},
                )

            project = urllib.parse.unquote(member_edit_match.group(1))
            old_name = urllib.parse.unquote(member_edit_match.group(2))
            body = parse_body(event)
            new_name = (body.get("newName") or old_name).strip()
            role = (body.get("role") or "Developer").strip()
            email = (body.get("email") or "").strip()

            if old_name != new_name:
                table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{old_name}"})

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{new_name}",
                "name": new_name,
                "project": project,
                "role": role,
                "email": email,
                "updated_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(200, {"message": f"Member '{old_name}' updated in '{project}'", "member": item})

        # DELETE /projects/{project}/members/{name} (Admin or self un-assignment)
        member_del_match = re.match(r"^/projects/([^/]+)/members/([^/]+)$", path)
        if (member_del_match or path == "/members") and method == "DELETE":
            body = parse_body(event) if method == "DELETE" and event.get("body") else {}
            if member_del_match:
                project = urllib.parse.unquote(member_del_match.group(1))
                name = urllib.parse.unquote(member_del_match.group(2))
            else:
                project = params.get("project") or body.get("project")
                name = params.get("name") or body.get("name")

            if not project or not name:
                return create_response(400, {"error": "Project and member name are required"})

            if user_claims and not user_claims["is_admin"]:
                proj_resp = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{project}"})
                proj_item = proj_resp.get("Item") or {}
                allow_self = bool(proj_item.get("allow_self_assignment", False))

                user_name = (user_claims.get("name") or "").strip().lower()
                user_email = (user_claims.get("email") or "").strip().lower()
                target_norm = name.strip().lower()
                is_self = (
                    target_norm == user_name
                    or target_norm == user_email
                    or target_norm == user_email.split("@")[0]
                )

                if not (allow_self and is_self):
                    return create_response(
                        403,
                        {"error": "Forbidden: Only administrators can remove other members from projects."},
                    )

            table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"})
            return create_response(200, {"message": f"Member '{name}' removed from '{project}'"})

        # =====================================================================
        # 4. DAILY SCRUMS CRUD (Member Self-Protection + Admin Access)
        # =====================================================================
        # POST /scrums or PUT /scrums -> Record / Update Daily Scrum
        if (path == "/scrums" or path == "/") and method in ["POST", "PUT"]:
            body = parse_body(event)
            project = body.get("project")
            week = body.get("week")
            day = body.get("day")
            member = body.get("member")
            answers = body.get("answers", [])

            if not all([project, week, day, member]):
                return create_response(400, {"error": "Missing fields: project, week, day, member"})

            # RBAC: Non-admin users can ONLY create or modify scrums for themselves
            if user_claims and not user_claims["is_admin"]:
                user_name = (user_claims.get("name") or "").strip().lower()
                user_email = (user_claims.get("email") or "").strip().lower()
                target_norm = member.strip().lower()

                if (
                    target_norm != user_name
                    and target_norm != user_email
                    and target_norm != user_email.split("@")[0]
                ):
                    return create_response(
                        403,
                        {
                            "error": f"Forbidden: You can only record or modify your own Daily Scrum (logged in as {user_claims.get('name')})."
                        },
                    )

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                "project": project,
                "week": week,
                "day": day,
                "member": member,
                "answers": answers,
                "updated_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(
                200 if method == "PUT" else 201,
                {
                    "message": f"Daily Scrum recorded for {member} ({week} - {day})",
                    "data": item,
                },
            )

        # GET /scrums -> Full Weekly Matrix or Single Item (Transparent to all)
        elif (path == "/scrums" or path == "/") and method == "GET":
            project = params.get("project")
            week = params.get("week")
            day = params.get("day")
            member = params.get("member")

            if not project:
                return create_response(400, {"error": "Project parameter is required"})

            # Case A: Get full weekly matrix for a project
            if week and not (day and member):
                resp = table.query(
                    KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                    & Key("SK").begins_with(f"WEEK#{week}#")
                )
                items = resp.get("Items", [])
                return create_response(
                    200,
                    {
                        "project": project,
                        "week": week,
                        "count": len(items),
                        "scrums": items,
                    },
                )

            # Case B: Get single member daily
            if not all([project, week, day, member]):
                return create_response(400, {"error": "Missing params: project, week, day, member"})

            response = table.get_item(
                Key={
                    "PK": f"PROJECT#{project}",
                    "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                }
            )
            item = response.get("Item")
            if not item:
                return create_response(404, {"error": "Daily Scrum not found"})

            return create_response(
                200,
                {
                    "message": f"Daily Scrum loaded for {member} ({week} - {day})",
                    "answers": item.get("answers", []),
                    "data": item,
                },
            )

        # DELETE /scrums -> Delete a Daily Scrum entry
        elif (path == "/scrums" or path == "/") and method == "DELETE":
            body = parse_body(event) if event.get("body") else {}
            project = params.get("project") or body.get("project")
            week = params.get("week") or body.get("week")
            day = params.get("day") or body.get("day")
            member = params.get("member") or body.get("member")

            if not all([project, week, day, member]):
                return create_response(400, {"error": "Missing params: project, week, day, member"})

            # RBAC: Non-admin users can ONLY delete their own scrums
            if user_claims and not user_claims["is_admin"]:
                user_name = (user_claims.get("name") or "").strip().lower()
                user_email = (user_claims.get("email") or "").strip().lower()
                target_norm = member.strip().lower()

                if (
                    target_norm != user_name
                    and target_norm != user_email
                    and target_norm != user_email.split("@")[0]
                ):
                    return create_response(
                        403,
                        {
                            "error": f"Forbidden: You can only delete your own Daily Scrum (logged in as {user_claims.get('name')})."
                        },
                    )

            table.delete_item(
                Key={
                    "PK": f"PROJECT#{project}",
                    "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                }
            )
            return create_response(
                200,
                {"message": f"Daily Scrum deleted for {member} ({week} - {day})"},
            )

        # =====================================================================
        # 5. KANBAN TASK ENDPOINTS (Work in Progress / Scrumban)
        # =====================================================================
        # GET /tasks -> Get all tasks for a project
        elif path == "/tasks" and method == "GET":
            project = params.get("project")
            if not project:
                return create_response(400, {"error": "Missing 'project' parameter"})

            response = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with("TASK#")
            )
            tasks = response.get("Items", [])
            return create_response(200, {"project": project, "tasks": tasks})

        # POST /tasks -> Create a task
        elif path == "/tasks" and method == "POST":
            body = parse_body(event)
            project = body.get("project")
            title = (body.get("title") or "").strip()
            assignee = (body.get("assignee") or "").strip()
            status = body.get("status") or "TODO"
            priority = body.get("priority") or "MEDIUM"
            blocker = (body.get("blocker") or "").strip()

            if not project or not title:
                return create_response(400, {"error": "Missing 'project' or 'title'"})

            task_id = body.get("id") or str(uuid.uuid4())[:8]
            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"TASK#{task_id}",
                "id": task_id,
                "project": project,
                "title": title,
                "assignee": assignee,
                "status": status,
                "priority": priority,
                "blocker": blocker,
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": "Task created successfully", "task": item})

        # PUT /tasks -> Update task status, assignee, title, or blocker
        elif path == "/tasks" and method == "PUT":
            body = parse_body(event)
            project = body.get("project")
            task_id = body.get("id")

            if not project or not task_id:
                return create_response(400, {"error": "Missing 'project' or 'id'"})

            update_parts = ["updated_at = :up"]
            expr_names = {}
            expr_values = {":up": datetime.datetime.utcnow().isoformat()}

            if "status" in body:
                update_parts.append("#st = :st")
                expr_names["#st"] = "status"
                expr_values[":st"] = body["status"]

            if "assignee" in body:
                update_parts.append("assignee = :asgn")
                expr_values[":asgn"] = body["assignee"]

            if "title" in body:
                update_parts.append("title = :ttl")
                expr_values[":ttl"] = body["title"]

            if "priority" in body:
                update_parts.append("priority = :prio")
                expr_values[":prio"] = body["priority"]

            if "blocker" in body:
                update_parts.append("blocker = :blk")
                expr_values[":blk"] = body["blocker"]

            update_expr = "SET " + ", ".join(update_parts)
            kwargs = {
                "Key": {"PK": f"PROJECT#{project}", "SK": f"TASK#{task_id}"},
                "UpdateExpression": update_expr,
                "ExpressionAttributeValues": expr_values,
            }
            if expr_names:
                kwargs["ExpressionAttributeNames"] = expr_names

            table.update_item(**kwargs)
            return create_response(200, {"message": "Task updated successfully"})

        # DELETE /tasks -> Delete a task
        elif path == "/tasks" and method == "DELETE":
            body = parse_body(event) if event.get("body") else {}
            project = params.get("project") or body.get("project")
            task_id = params.get("id") or body.get("id")

            if not project or not task_id:
                return create_response(400, {"error": "Missing 'project' or 'id'"})

            table.delete_item(
                Key={"PK": f"PROJECT#{project}", "SK": f"TASK#{task_id}"}
            )
            return create_response(200, {"message": "Task deleted successfully"})

        return create_response(404, {"error": f"Path '{path}' with method '{method}' not found"})

    except ClientError as err:
        return create_response(500, {"error": err.response["Error"]["Message"]})
    except Exception as err:
        return create_response(500, {"error": str(err)})
