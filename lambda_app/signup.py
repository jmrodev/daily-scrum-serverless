"""POST /auth/signup — register + verification email."""
import datetime
import secrets
import time
import urllib.parse

from .activity import log_user_activity
from .mail import get_email_config, send_email
from .store import create_response, parse_body, table
from .templates import signup_html
from .tokens import hash_password


def route(path, method, event, params, user_claims):
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
        sep = "&" if "?" in app_url else "?"
        activation_url = f"{app_url}{sep}action=activate&email={urllib.parse.quote(email)}&code={code}"
        subject = f"{code} es tu código de activación - Daily Scrum"
        success, res = send_email(email, subject, signup_html(name, code, activation_url))
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

    return None
