"""Passwordless OTP: request (throttled) + verify (attempt-capped)."""
import datetime
import secrets
import time
import uuid

from .activity import log_user_activity
from .mail import get_email_config, send_email
from .store import create_response, parse_body, table
from .templates import otp_html
from .tokens import TOKEN_TTL_SECONDS, get_user_groups, mint_token


def route(path, method, event, params, user_claims):
    # POST /auth/otp/request -> Passwordless OTP request via Email
    if path == "/auth/otp/request" and method == "POST":
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

        # Throttle: 1 envío por minuto + bloqueo 5 min tras 5 intentos fallidos
        existing_otp = table.get_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"}).get("Item")
        if existing_otp:
            last_sent = int(existing_otp.get("last_sent") or 0)
            prev_attempts = int(existing_otp.get("attempts") or 0)
            if prev_attempts >= 5 and (now - last_sent) < 300:
                return create_response(429, {"error": "Demasiados intentos fallidos. Esperá 5 minutos y solicitá un código nuevo."})
            if last_sent and (now - last_sent) < 60:
                return create_response(429, {"error": "Ya enviamos un código. Esperá un minuto antes de pedir otro."})

        otp_item = {
            "PK": "AUTH#OTP",
            "SK": f"EMAIL#{email}",
            "email": email,
            "code": code,
            "ttl": ttl,
            "attempts": 0,
            "last_sent": now,
            "created_at": datetime.datetime.utcnow().isoformat(),
        }
        table.put_item(Item=otp_item)

        app_url = email_cfg.get("app_url") or "https://jmrodev.github.io/daily-scrum-serverless/"
        subject = f"{code} es tu código de acceso a Daily Scrum"
        success, res = send_email(email, subject, otp_html(code, app_url))
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
            return create_response(400, {"error": "Código inválido o expirado. Solicitá uno nuevo."})

        now = int(time.time())
        if otp_item.get("ttl", 0) < now:
            table.delete_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"})
            return create_response(400, {"error": "El código ha expirado (10 min de validez). Solicitá uno nuevo."})

        attempts = int(otp_item.get("attempts") or 0)
        if attempts >= 5:
            table.delete_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"})
            return create_response(429, {"error": "Demasiados intentos fallidos. Solicitá un código nuevo."})

        if otp_item.get("code") != code:
            table.update_item(
                Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"},
                UpdateExpression="SET attempts = :a",
                ExpressionAttributeValues={":a": attempts + 1},
            )
            return create_response(400, {"error": "Código inválido o expirado. Solicitá uno nuevo."})

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

    return None
