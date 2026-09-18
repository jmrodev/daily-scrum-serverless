import base64
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "DailyScrum")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")
# HMAC secret for server-minted session tokens. Injected via deploy.sh
# (openssl rand -hex 32). Never shipped to the browser. Empty = misconfigured.
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "")
TOKEN_TTL_SECONDS = 86400 * 7  # 7 days, preserved to avoid session-churn change

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
cognito_idp = boto3.client("cognito-idp")

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
}


def create_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": RESPONSE_HEADERS,
        "body": json.dumps(body),
    }


def parse_body(event):
    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    return json.loads(raw_body) if isinstance(raw_body, str) else raw_body


def _b64url_encode(data):
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(segment):
    segment += "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode(segment.encode("utf-8"))


def mint_token(payload):
    """Mint an HMAC-SHA256 server token: b64(header).b64(payload).b64(sig).

    PBKDF2 password hashing stays in hash_password/verify_password (100k rounds).
    Fails closed (raises) when TOKEN_SECRET is not configured.
    """
    if not TOKEN_SECRET:
        raise RuntimeError("TOKEN_SECRET is not configured on the server")
    header_b64 = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(TOKEN_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_b64}.{payload_b64}.{_b64url_encode(sig)}"


def verify_token(token):
    """Verify HMAC signature + expiry. Returns payload dict or None."""
    if not token or not TOKEN_SECRET:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected = hmac.new(TOKEN_SECRET.encode("utf-8"), signing_input, hashlib.sha256).digest()
        provided = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected, provided):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        exp = payload.get("exp")
        if exp and exp < time.time():
            return None
        return payload
    except Exception:
        return None


def get_user_groups(email):
    """Read canonical role groups from DDB USER# profile. Never derive from email."""
    try:
        resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
        item = resp.get("Item") or {}
        groups = item.get("groups") or []
        if isinstance(groups, str):
            groups = [groups]
        return list(groups) if groups else ["Members"]
    except Exception:
        return ["Members"]


def extract_user_claims(event):
    """Extract and verify user claims from Authorization: Bearer <token>.

    Primary: HMAC server tokens minted by mint_token (signature + exp verified).
    Fallback-only: Cognito IdP tokens (accepted by issuer shape when CLIENT_ID is
    configured; RS256 cannot be verified with stdlib-only deps — see docs).
    Legacy unsigned tokens (auth_sig / otp_signature suffix convention) are
    rejected: their signatures never match TOKEN_SECRET.
    """
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:].strip()
    claims = verify_token(token)
    if claims is not None:
        email = claims.get("email") or ""
        name = claims.get("name") or (email.split("@")[0] if email else "")
        groups = claims.get("cognito:groups") or claims.get("groups") or []
        if isinstance(groups, str):
            groups = [groups]
        is_admin = bool(claims.get("is_admin", False)) or "Admins" in groups
        return {
            "email": email,
            "name": name,
            "groups": groups,
            "is_admin": is_admin,
            "role": claims.get("role") or ("admin" if is_admin else "member"),
            "sub": claims.get("sub", ""),
        }

    # Fallback-only path: Cognito-minted token (USER_PASSWORD_AUTH via CLIENT_ID).
    # Accepted by payload shape; admin derives ONLY from the cognito:groups claim.
    if CLIENT_ID:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            payload = json.loads(_b64url_decode(parts[1]).decode("utf-8"))
            iss = payload.get("iss") or ""
            if "cognito-idp" not in iss:
                return None
            exp = payload.get("exp")
            if exp and exp < time.time():
                return None
            email = payload.get("email") or payload.get("username") or ""
            groups = payload.get("cognito:groups") or []
            if isinstance(groups, str):
                groups = [groups]
            is_admin = "Admins" in groups
            return {
                "email": email,
                "name": payload.get("name") or (email.split("@")[0] if email else ""),
                "groups": groups,
                "is_admin": is_admin,
                "role": "admin" if is_admin else "member",
                "sub": payload.get("sub", ""),
            }
        except Exception:
            return None
    return None


def require_auth(event, admin_only=False):
    """Gate helper: 401 without a valid Bearer, 403 for non-admin on admin routes."""
    claims = extract_user_claims(event)
    if not claims:
        return None, create_response(401, {"error": "Unauthorized: valid session required"})
    if admin_only and not claims.get("is_admin"):
        return None, create_response(403, {"error": "Forbidden: administrators only"})
    return claims, None


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


def get_email_config():
    """Retrieve Gmail SMTP configuration from DynamoDB (CONFIG#EMAIL) or environment."""
    gmail_user = os.environ.get("GMAIL_USER", "")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    sender_name = os.environ.get("GMAIL_SENDER_NAME", "Daily Scrum")
    app_url = os.environ.get("APP_URL", "https://jmrodev.github.io/daily-scrum-serverless/")

    try:
        resp = table.get_item(Key={"PK": "CONFIG#SYSTEM", "SK": "CONFIG#EMAIL"})
        item = resp.get("Item")
        if item:
            gmail_user = item.get("gmail_user") or gmail_user
            gmail_password = item.get("gmail_password") or gmail_password
            sender_name = item.get("sender_name") or sender_name
            app_url = item.get("app_url") or app_url
    except Exception:
        pass

    return {
        "gmail_user": gmail_user.strip(),
        "gmail_password": gmail_password.strip().replace(" ", ""),
        "sender_name": sender_name.strip(),
        "app_url": app_url.strip(),
    }


def send_email(to_email, subject, html_body):
    """Send an email using Gmail SMTP via standard smtplib without external dependencies."""
    cfg = get_email_config()
    gmail_user = cfg.get("gmail_user")
    app_pwd = cfg.get("gmail_password")
    sender_name = cfg.get("sender_name") or "Daily Scrum"

    if not gmail_user or not app_pwd:
        return False, "El servicio de correo (Gmail SMTP) no está configurado por el administrador."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{sender_name} <{gmail_user}>"
    msg["To"] = to_email
    msg["Reply-To"] = gmail_user

    part = MIMEText(html_body, "html", "utf-8")
    msg.attach(part)

    try:
        # Connect to Gmail SMTP over SSL (Port 465)
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=12) as server:
            server.login(gmail_user, app_pwd)
            server.sendmail(gmail_user, [to_email], msg.as_string())
        return True, "Email enviado exitosamente"
    except smtplib.SMTPAuthenticationError:
        return False, "Error de autenticación de Gmail: verificá tu correo y la contraseña de aplicación de 16 letras."
    except Exception:
        # Fallback try port 587 with STARTTLS if port 465 timed out or had issue
        try:
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=12) as server:
                server.starttls()
                server.login(gmail_user, app_pwd)
                server.sendmail(gmail_user, [to_email], msg.as_string())
            return True, "Email enviado exitosamente"
        except Exception as e2:
            return False, f"Fallo al enviar correo con Gmail SMTP: {str(e2)}"


def log_user_activity(email, action, event=None):
    """Record user activity (LOGIN, SIGNUP, CONFIRM, OTP_VERIFY) in DynamoDB.
    Updates USER#{email} PROFILE (last_login, login_count) and logs to AUDIT#USER#{email}.
    """
    if not email:
        return
    email = email.strip().lower()
    now_iso = datetime.datetime.utcnow().isoformat()
    ip = ""
    ua = ""
    if event:
        http_ctx = event.get("requestContext", {}).get("http", {})
        ip = http_ctx.get("sourceIp") or event.get("requestContext", {}).get("identity", {}).get("sourceIp", "")
        headers = event.get("headers") or {}
        ua = headers.get("user-agent", "")

    # 1. Update USER#{email} PROFILE item
    try:
        table.update_item(
            Key={"PK": f"USER#{email}", "SK": "PROFILE"},
            UpdateExpression="SET last_login = :now, updated_at = :now ADD login_count :inc",
            ExpressionAttributeValues={":now": now_iso, ":inc": 1},
        )
    except Exception as e:
        print(f"Error updating user profile login count for {email}: {e}")

    # 2. Record chronological audit item
    try:
        event_id = str(uuid.uuid4())[:8]
        audit_item = {
            "PK": f"AUDIT#USER#{email}",
            "SK": f"EVENT#{now_iso}#{event_id}",
            "action": action,
            "email": email,
            "timestamp": now_iso,
            "ip": ip,
            "user_agent": ua[:160],
            "ttl": int(time.time()) + (86400 * 90),
        }
        table.put_item(Item=audit_item)
    except Exception as e:
        print(f"Error recording audit event for {email}: {e}")


def handler(event, context):
    http_context = event.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET")
    raw_path = event.get("rawPath", "/")
    path = raw_path.rstrip("/")
    if not path:
        path = "/"

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": RESPONSE_HEADERS}

    params = event.get("queryStringParameters") or {}
    user_claims = extract_user_claims(event)

    try:
        # =====================================================================
        # 1. AUTH ENDPOINTS (Cognito Integration)
        # =====================================================================
        # POST /auth/signup -> Register user with Email + Password, sending verification code via Email (Gmail SMTP)
        if path == "/auth/signup" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            password = body.get("password") or ""
            name = (body.get("name") or email.split("@")[0]).strip()

            if not email or "@" not in email:
                return create_response(400, {"error": "Email válido es requerido"})
            if not password or len(password) < 8:
                return create_response(400, {"error": "La contraseña debe tener al menos 8 caracteres"})

            # Email Service check
            email_cfg = get_email_config()
            if not email_cfg.get("gmail_user") or not email_cfg.get("gmail_password"):
                return create_response(400, {
                    "error": "El servicio de email (Gmail SMTP) no está configurado por el administrador. Es obligatorio para verificar cuentas nuevas."
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
                "groups": ["Members"],
                "verification_code": code,
                "code_ttl": ttl,
                "created_at": datetime.datetime.utcnow().isoformat(),
            }
            table.put_item(Item=user_item)

            # Send verification code
            app_url = email_cfg.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"
            subject = f"{code} es tu código de activación - Daily Scrum"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
              <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">¡Bienvenido a Daily Scrum, {name}!</h2>
              <p style="color: #334155; font-size: 14px;">Para activar tu cuenta, ingresá el siguiente código de verificación de 6 dígitos:</p>
              <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 20px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
                {code}
              </div>
              <div style="text-align: center; margin: 24px 0;">
                <a href="{app_url}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; display: inline-block;">Abrir Daily Scrum</a>
              </div>
              <p style="color: #64748b; font-size: 12px; text-align: center; margin: 8px 0;">Enlace directo: <a href="{app_url}" style="color: #0284c7;">{app_url}</a></p>
              <p style="color: #64748b; font-size: 12px; margin-top: 16px; margin-bottom: 0; border-top: 1px solid #f1f5f9; padding-top: 12px;">Este código vence en 15 minutos. Si no te registraste, podés desestimar este email.</p>
            </div>
            """
            success, res = send_email(email, subject, html)
            if not success:
                return create_response(500, {
                    "error": f"Fallo al despachar email de verificación ({res})."
                })

            log_user_activity(email, "SIGNUP", event)
            return create_response(201, {
                "message": "Usuario registrado. Te enviamos el código de 6 dígitos a tu correo.",
                "email": email,
                "name": name,
            })

        # POST /auth/confirm -> Confirm user registration code or activate invited user
        elif path == "/auth/confirm" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            code = (body.get("code") or "").strip()
            password = body.get("password") or ""

            if not email or not code:
                return create_response(400, {"error": "Email y código de verificación son requeridos"})

            user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
            user_item = user_resp.get("Item")
            if not user_item:
                return create_response(404, {"error": "Usuario no encontrado"})

            # Check verification code & expiry
            stored_code = user_item.get("verification_code")
            code_ttl = user_item.get("code_ttl", 0)
            now = int(time.time())

            if not stored_code or stored_code != code:
                return create_response(400, {"error": "Código de verificación incorrecto"})

            if code_ttl and now > code_ttl:
                return create_response(400, {"error": "El código de verificación ha expirado. Solicitá uno nuevo registrándote de nuevo."})

            # If user was invited (FORCE_CHANGE_PASSWORD), require new password
            update_expr = "SET #st = :status, updated_at = :up REMOVE verification_code, code_ttl"
            expr_names = {"#st": "status"}
            expr_values = {
                ":status": "CONFIRMED",
                ":up": datetime.datetime.utcnow().isoformat(),
            }

            if password:
                if len(password) < 8:
                    return create_response(400, {"error": "La contraseña debe tener al menos 8 caracteres"})
                update_expr += ", password_hash = :ph"
                expr_values[":ph"] = hash_password(password)

            table.update_item(
                Key={"PK": f"USER#{email}", "SK": "PROFILE"},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )

            # Role comes from DDB groups, never from the email address.
            groups = get_user_groups(email)
            is_admin = "Admins" in groups
            name = user_item.get("name") or email.split("@")[0].capitalize()
            now = int(time.time())
            sub = str(uuid.uuid4())
            payload = {
                "sub": sub,
                "email": email,
                "name": name,
                "cognito:groups": groups,
                "groups": groups,
                "is_admin": is_admin,
                "role": "admin" if is_admin else "member",
                "iat": now,
                "exp": now + TOKEN_TTL_SECONDS,
            }
            try:
                token = mint_token(payload)
            except Exception:
                token = None

            log_user_activity(email, "CONFIRM", event)
            return create_response(200, {
                "message": "¡Cuenta activada y verificada exitosamente!",
                "idToken": token,
                "accessToken": token,
                "user": {
                    "email": email,
                    "name": name,
                    "groups": groups,
                    "is_admin": is_admin,
                    "role": "admin" if is_admin else "member",
                    "sub": sub,
                } if token else None,
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

            if user_item:
                if user_item.get("status") == "FORCE_CHANGE_PASSWORD" or not user_item.get("password_hash"):
                    return create_response(403, {
                        "error": "Tu cuenta requiere activación. Ingresá a 'Activar Cuenta' con el código de 6 dígitos que recibiste por correo y definí tu contraseña.",
                        "requires_activation": True,
                        "email": email,
                    })

                if user_item.get("status") == "PENDING_VERIFICATION":
                    return create_response(403, {
                        "error": "Tu cuenta aún no está confirmada. Ingresá el código enviado a tu correo.",
                        "requires_confirmation": True,
                        "email": email,
                    })

                if not verify_password(password, user_item.get("password_hash")):
                    return create_response(401, {"error": "Contraseña incorrecta"})

                # Role comes from DDB groups, never from the email address.
                groups = get_user_groups(email)
                is_admin = "Admins" in groups
                name = user_item.get("name") or email.split("@")[0].capitalize()
                now = int(time.time())
                sub = str(uuid.uuid4())
                payload = {
                    "sub": sub,
                    "email": email,
                    "name": name,
                    "cognito:groups": groups,
                    "groups": groups,
                    "is_admin": is_admin,
                    "role": "admin" if is_admin else "member",
                    "iat": now,
                    "exp": now + TOKEN_TTL_SECONDS,
                }
                try:
                    token = mint_token(payload)
                except RuntimeError:
                    return create_response(500, {"error": "Server auth is misconfigured (TOKEN_SECRET)"})

                log_user_activity(email, "LOGIN", event)
                return create_response(200, {
                    "message": "Login exitoso",
                    "idToken": token,
                    "accessToken": token,
                    "user": {
                        "email": email,
                        "name": name,
                        "groups": groups,
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

        # POST /auth/otp/request -> Passwordless OTP request via Email
        elif path == "/auth/otp/request" and method == "POST":
            body = parse_body(event)
            email = (body.get("email") or "").strip().lower()
            if not email or "@" not in email:
                return create_response(400, {"error": "Email válido es requerido"})

            email_cfg = get_email_config()
            if not email_cfg.get("gmail_user") or not email_cfg.get("gmail_password"):
                return create_response(400, {
                    "error": "El servicio de email (Gmail SMTP) no está configurado por el administrador. Es obligatorio para enviar códigos."
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

            app_url = email_cfg.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"
            subject = f"{code} es tu código de acceso a Daily Scrum"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
              <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">Daily Scrum & Kanban</h2>
              <p style="color: #334155; font-size: 14px;">Tu código de verificación de un solo uso para iniciar sesión es:</p>
              <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 20px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
                {code}
              </div>
              <div style="text-align: center; margin: 20px 0;">
                <a href="{app_url}" style="background-color: #0284c7; color: #ffffff; padding: 10px 22px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 13px; display: inline-block;">Ingresar a la Plataforma</a>
              </div>
              <p style="color: #64748b; font-size: 12px; text-align: center; margin: 8px 0;">Enlace directo: <a href="{app_url}" style="color: #0284c7;">{app_url}</a></p>
              <p style="color: #64748b; font-size: 12px; margin-top: 14px; margin-bottom: 0; border-top: 1px solid #f1f5f9; padding-top: 10px;">Válido por 10 minutos.</p>
            </div>
            """
            success, res = send_email(email, subject, html)
            if success:
                return create_response(200, {
                    "message": f"Código enviado con éxito a {email}",
                    "sent": True,
                })
            else:
                return create_response(500, {
                    "error": f"Error al despachar email ({res}). Verificá la configuración de email.",
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

            # Role comes from DDB groups, never from the email address.
            groups = get_user_groups(email)
            is_admin = "Admins" in groups

            user_name = email.split("@")[0].capitalize()
            now = int(time.time())
            sub = str(uuid.uuid4())
            payload = {
                "sub": sub,
                "email": email,
                "name": user_name,
                "cognito:groups": groups,
                "groups": groups,
                "is_admin": is_admin,
                "role": "admin" if is_admin else "member",
                "iat": now,
                "exp": now + TOKEN_TTL_SECONDS,
            }

            try:
                token = mint_token(payload)
            except RuntimeError:
                return create_response(500, {"error": "Server auth is misconfigured (TOKEN_SECRET)"})

            claims = {
                "email": email,
                "name": user_name,
                "groups": groups,
                "is_admin": is_admin,
                "role": "admin" if is_admin else "member",
                "sub": sub,
            }

            log_user_activity(email, "OTP_VERIFY", event)
            return create_response(200, {
                "message": "Login exitoso",
                "idToken": token,
                "accessToken": token,
                "user": claims,
            })

        # GET /admin/config/email (Admin only)
        elif path in ("/admin/config/email", "/admin/config/resend") and method == "GET":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Solo administradores pueden ver la configuración de email."})

            cfg = get_email_config()
            gmail_user = cfg.get("gmail_user") or ""
            has_pwd = bool(cfg.get("gmail_password"))
            sender_name = cfg.get("sender_name") or "Daily Scrum"
            app_url = cfg.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"

            return create_response(200, {
                "configured": bool(gmail_user and has_pwd),
                "gmailUser": gmail_user,
                "senderName": sender_name,
                "appUrl": app_url,
                "hasPassword": has_pwd,
                "passwordMasked": "••••••••" if has_pwd else "",
            })

        # POST /admin/config/email (Admin only)
        elif path in ("/admin/config/email", "/admin/config/resend", "/admin/resend-config") and method == "POST":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Solo administradores pueden actualizar la configuración de email."})

            body = parse_body(event)
            gmail_user = (body.get("gmailUser") or body.get("gmail_user") or "").strip().lower()
            gmail_password = (body.get("gmailPassword") or body.get("gmail_password") or body.get("apiKey") or body.get("api_key") or "").strip().replace(" ", "")
            sender_name = (body.get("senderName") or body.get("sender_name") or body.get("fromEmail") or "Daily Scrum").strip()
            app_url = (body.get("appUrl") or body.get("app_url") or "").strip()

            existing = get_email_config()
            if not gmail_user and existing.get("gmail_user"):
                gmail_user = existing.get("gmail_user")
            if not gmail_password and existing.get("gmail_password"):
                gmail_password = existing.get("gmail_password")
            if not app_url:
                app_url = existing.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"

            if not gmail_user or not gmail_password:
                return create_response(400, {"error": "Correo de Gmail y Contraseña de Aplicación (16 letras) son requeridos."})

            item = {
                "PK": "CONFIG#SYSTEM",
                "SK": "CONFIG#EMAIL",
                "gmail_user": gmail_user,
                "gmail_password": gmail_password,
                "sender_name": sender_name,
                "app_url": app_url,
                "updated_at": datetime.datetime.utcnow().isoformat(),
                "updated_by": user_claims.get("email"),
            }
            table.put_item(Item=item)
            return create_response(200, {"message": "Configuración de Gmail SMTP guardada exitosamente."})

        # POST /admin/config/email/test (Admin only)
        elif path in ("/admin/config/email/test", "/admin/config/resend/test") and method == "POST":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Solo administradores pueden probar la configuración de email."})

            body = parse_body(event)
            to_email = (body.get("toEmail") or body.get("to") or body.get("email") or user_claims.get("email") or "").strip()
            if not to_email or "@" not in to_email:
                return create_response(400, {"error": "Email destino válido requerido"})

            cfg = get_email_config()
            if not cfg.get("gmail_user") or not cfg.get("gmail_password"):
                return create_response(400, {"error": "No hay credenciales de Gmail SMTP configuradas aún."})

            app_url = cfg.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"
            subject = "🧪 Prueba de Configuración - Daily Scrum"
            html = f"""
            <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #10b981; border-radius: 12px; background: #ffffff;">
              <h2 style="color: #10b981; margin-top: 0; font-size: 20px;">¡Conexión Exitosa con Gmail SMTP!</h2>
              <p style="color: #334155; font-size: 14px;">Este es un correo de prueba generado desde el panel de administración de <strong>Daily Scrum & Kanban</strong>.</p>
              <p style="color: #334155; font-size: 14px;">La cuenta <code>{cfg.get('gmail_user')}</code> y el remitente <strong>{cfg.get('sender_name')}</strong> están funcionando a la perfección.</p>
              <div style="text-align: center; margin: 20px 0;">
                <a href="{app_url}" style="background-color: #10b981; color: #ffffff; padding: 10px 22px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 13px; display: inline-block;">Abrir Daily Scrum</a>
              </div>
              <p style="color: #64748b; font-size: 12px; text-align: center;">URL configurada: <a href="{app_url}" style="color: #0284c7;">{app_url}</a></p>
              <p style="color: #64748b; font-size: 12px; margin-top: 24px; margin-bottom: 0;">Enviado vía Gmail SMTP: {datetime.datetime.utcnow().isoformat()}</p>
            </div>
            """
            success, res = send_email(to_email, subject, html)
            if success:
                return create_response(200, {"message": f"Email de prueba enviado exitosamente a {to_email}"})
            else:
                return create_response(400, {"error": f"Fallo al enviar correo con Gmail: {res}"})

        # GET /admin/audit/activity (Admin only) -> Member login & signup activity metrics
        elif path == "/admin/audit/activity" and method == "GET":
            if not user_claims or not user_claims.get("is_admin"):
                return create_response(403, {"error": "Forbidden: Solo administradores pueden ver la auditoría de actividad."})

            project = params.get("project")
            member_emails = set()
            member_details = {}

            if project:
                resp = table.query(
                    KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                    & Key("SK").begins_with("MEMBER#")
                )
                for item in resp.get("Items", []):
                    em = (item.get("email") or "").strip().lower()
                    if em:
                        member_emails.add(em)
                        member_details[em] = {
                            "name": item.get("name") or em.split("@")[0],
                            "role": item.get("role") or "Developer",
                            "is_admin": bool(item.get("is_admin", False)),
                        }

            # If no project specified or no member emails found, scan all USER# profiles
            if not member_emails:
                users_scan = table.scan(
                    FilterExpression=Key("PK").begins_with("USER#") & Key("SK").eq("PROFILE")
                )
                for item in users_scan.get("Items", []):
                    em = (item.get("email") or "").strip().lower()
                    if em:
                        member_emails.add(em)
                        groups = item.get("groups") or []
                        member_details[em] = {
                            "name": item.get("name") or em.split("@")[0],
                            "role": "Admin" if "Admins" in groups else "Member",
                            "is_admin": "Admins" in groups,
                        }

            activity_records = []
            for em in sorted(member_emails):
                p_resp = table.get_item(Key={"PK": f"USER#{em}", "SK": "PROFILE"})
                p_item = p_resp.get("Item") or {}

                a_resp = table.query(
                    KeyConditionExpression=Key("PK").eq(f"AUDIT#USER#{em}")
                    & Key("SK").begins_with("EVENT#"),
                    ScanIndexForward=False,
                    Limit=30,
                )
                events = [
                    {
                        "action": ev.get("action", "LOGIN"),
                        "timestamp": ev.get("timestamp", ""),
                        "ip": ev.get("ip", ""),
                    }
                    for ev in a_resp.get("Items", [])
                ]

                created_at = p_item.get("created_at") or ""
                last_login = p_item.get("last_login") or (events[0]["timestamp"] if events else created_at)
                login_count = int(p_item.get("login_count") or (len(events) if events else (1 if last_login else 0)))
                status = p_item.get("status") or ("CONFIRMED" if p_item.get("password_hash") else "INVITED")
                info = member_details.get(em, {})

                activity_records.append({
                    "email": em,
                    "name": p_item.get("name") or info.get("name") or em.split("@")[0],
                    "role": info.get("role") or "Developer",
                    "is_admin": bool(info.get("is_admin", False) or "Admins" in (p_item.get("groups") or [])),
                    "status": status,
                    "created_at": created_at,
                    "last_login": last_login,
                    "login_count": login_count,
                    "events": events,
                })

            return create_response(200, {
                "project": project or "ALL",
                "activity": activity_records,
                "server_time": datetime.datetime.utcnow().isoformat(),
            })


        # =====================================================================
        # 2. PROJECTS CRUD (Admin-Gated Modification)
        # =====================================================================
        # GET /projects (authenticated reads only)
        elif path == "/projects" and method == "GET":
            _, err = require_auth(event)
            if err:
                return err
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

        # POST /projects (Admin only)
        elif path == "/projects" and method == "POST":
            _, err = require_auth(event, admin_only=True)
            if err:
                return err

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
            _, err = require_auth(event, admin_only=True)
            if err:
                return err

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
            _, err = require_auth(event, admin_only=True)
            if err:
                return err

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
                    "is_admin": bool(item.get("is_admin", False)),
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
            email = (body.get("email") or "").strip().lower()
            system_role = (body.get("system_role") or "").strip().lower()
            is_admin = bool(body.get("is_admin", False)) or system_role in ["admin", "admins"]

            if not project or not name:
                return create_response(400, {"error": "Project and member name are required"})

            if not email:
                return create_response(400, {"error": "El correo electrónico es obligatorio para registrar al integrante."})

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
                is_admin = False

            # Check if user already exists in USER#{email}
            user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
            user_item = user_resp.get("Item")
            invite_email_sent = False
            invite_email_error = None

            now = int(time.time())
            groups = ["Admins"] if is_admin else ["Members"]

            if not user_item or user_item.get("status") in ["FORCE_CHANGE_PASSWORD", "PENDING_VERIFICATION"]:
                code = f"{secrets.randbelow(900000) + 100000}"
                ttl = now + 86400  # 24 hours validity

                user_record = {
                    "PK": f"USER#{email}",
                    "SK": "PROFILE",
                    "email": email,
                    "name": name,
                    "status": "FORCE_CHANGE_PASSWORD",
                    "groups": groups,
                    "verification_code": code,
                    "code_ttl": ttl,
                    "created_at": datetime.datetime.utcnow().isoformat(),
                }
                table.put_item(Item=user_record)

                # Send invitation via Email (Gmail SMTP)
                email_cfg = get_email_config()
                if email_cfg.get("gmail_user") and email_cfg.get("gmail_password"):
                    app_url = email_cfg.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"
                    role_badge = "Administrador" if is_admin else "Integrante"
                    subject = f"Invitación a Daily Scrum ({project}) - Activá tu cuenta"
                    html = f"""
                    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 24px; border: 1px solid #e2e8f0; border-radius: 12px; background: #ffffff;">
                      <h2 style="color: #0284c7; margin-top: 0; font-size: 20px;">¡Fuiste invitado a Daily Scrum!</h2>
                      <p style="color: #334155; font-size: 14px; line-height: 1.5;">
                        Hola <strong>{name}</strong>, te han asignado al proyecto <strong>{project}</strong> como <strong>{role}</strong> (Rol del sistema: <em>{role_badge}</em>).
                      </p>
                      <p style="color: #334155; font-size: 14px;">
                        Para activar tu cuenta y definir tu contraseña personal, usá el siguiente código de 6 dígitos:
                      </p>
                      <div style="font-size: 32px; font-weight: 800; letter-spacing: 8px; color: #0f172a; margin: 20px 0; padding: 14px; background: #f8fafc; border: 1px solid #cbd5e1; text-align: center; border-radius: 8px;">
                        {code}
                      </div>
                      <div style="text-align: center; margin: 24px 0;">
                        <a href="{app_url}" style="background-color: #0284c7; color: #ffffff; padding: 12px 24px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 14px; display: inline-block;">Activar mi Cuenta en Daily Scrum</a>
                      </div>
                      <p style="color: #64748b; font-size: 12px; text-align: center; margin: 8px 0;">Enlace directo a la app: <a href="{app_url}" style="color: #0284c7;">{app_url}</a></p>
                      <p style="color: #64748b; font-size: 12px; margin-top: 16px; margin-bottom: 0; border-top: 1px solid #f1f5f9; padding-top: 12px;">
                        Ingresá a la plataforma, seleccioná <strong>Activar Cuenta</strong>, colocá tu correo (<strong>{email}</strong>), este código de 6 dígitos y definí tu nueva contraseña.
                      </p>
                    </div>
                    """
                    sent, err_msg = send_email(email, subject, html)
                    invite_email_sent = sent
                    if not sent:
                        invite_email_error = err_msg
            else:
                # User exists and is confirmed. If admin explicitly updated role:
                current_groups = list(user_item.get("groups") or [])
                if is_admin and "Admins" not in current_groups:
                    current_groups.append("Admins")
                    table.update_item(
                        Key={"PK": f"USER#{email}", "SK": "PROFILE"},
                        UpdateExpression="SET groups = :g",
                        ExpressionAttributeValues={":g": current_groups},
                    )
                elif not is_admin and "Admins" in current_groups and (user_claims and user_claims.get("is_admin")):
                    current_groups = [g for g in current_groups if g != "Admins"]
                    if not current_groups:
                        current_groups = ["Members"]
                    table.update_item(
                        Key={"PK": f"USER#{email}", "SK": "PROFILE"},
                        UpdateExpression="SET groups = :g",
                        ExpressionAttributeValues={":g": current_groups},
                    )

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{name}",
                "name": name,
                "project": project,
                "role": role,
                "email": email,
                "is_admin": is_admin,
                "created_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(201, {
                "message": f"Member '{name}' added to '{project}'",
                "member": item,
                "invite_sent": invite_email_sent,
                "invite_error": invite_email_error,
            })

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
            email = (body.get("email") or "").strip().lower()
            system_role = (body.get("system_role") or "").strip().lower()
            has_is_admin = "is_admin" in body or bool(system_role)
            is_admin = bool(body.get("is_admin", False)) or (system_role in ["admin", "admins"])

            if old_name != new_name:
                table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{old_name}"})

            # If role updated and email exists, update USER profile groups
            if email and has_is_admin:
                user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
                user_item = user_resp.get("Item")
                if user_item:
                    current_groups = list(user_item.get("groups") or [])
                    if is_admin and "Admins" not in current_groups:
                        current_groups.append("Admins")
                    elif not is_admin and "Admins" in current_groups:
                        current_groups = [g for g in current_groups if g != "Admins"]
                        if not current_groups:
                            current_groups = ["Members"]
                    table.update_item(
                        Key={"PK": f"USER#{email}", "SK": "PROFILE"},
                        UpdateExpression="SET groups = :g",
                        ExpressionAttributeValues={":g": current_groups},
                    )

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{new_name}",
                "name": new_name,
                "project": project,
                "role": role,
                "email": email,
                "is_admin": is_admin,
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

            blocking_task_id = (body.get("blocking_task_id") or "").strip()
            blocking_task_title = (body.get("blocking_task_title") or "").strip()

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                "project": project,
                "week": week,
                "day": day,
                "member": member,
                "answers": answers,
                "blocking_task_id": blocking_task_id,
                "blocking_task_title": blocking_task_title,
                "updated_at": event.get("requestContext", {}).get("time", "") or datetime.datetime.utcnow().isoformat(),
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

            # Case A: Get all distinct weeks for a project (when week is omitted)
            if not week:
                resp = table.query(
                    KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                    & Key("SK").begins_with("WEEK#"),
                    ProjectionExpression="#w",
                    ExpressionAttributeNames={"#w": "week"},
                )
                items = resp.get("Items", [])
                weeks = list({item.get("week") for item in items if item.get("week")})
                def week_key(w):
                    try:
                        nums = re.findall(r"\d+", w)
                        return int(nums[0]) if nums else 0
                    except Exception:
                        return 0
                weeks.sort(key=week_key)
                return create_response(200, {"project": project, "weeks": weeks})

            # Case B: Get full weekly matrix for a project
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
            depends_on = body.get("depends_on") or []
            if isinstance(depends_on, str):
                depends_on = [depends_on] if depends_on else []
            blocked_by_task_id = (body.get("blocked_by_task_id") or "").strip()
            blocked_by_task_title = (body.get("blocked_by_task_title") or "").strip()

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
                "depends_on": depends_on,
                "blocked_by_task_id": blocked_by_task_id,
                "blocked_by_task_title": blocked_by_task_title,
                "created_at": datetime.datetime.utcnow().isoformat(),
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

            if "depends_on" in body:
                deps = body["depends_on"]
                if isinstance(deps, str):
                    deps = [deps] if deps else []
                update_parts.append("depends_on = :deps")
                expr_values[":deps"] = deps

            if "blocked_by_task_id" in body:
                update_parts.append("blocked_by_task_id = :bbtid")
                expr_values[":bbtid"] = body["blocked_by_task_id"]

            if "blocked_by_task_title" in body:
                update_parts.append("blocked_by_task_title = :bbttl")
                expr_values[":bbttl"] = body["blocked_by_task_title"]

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
