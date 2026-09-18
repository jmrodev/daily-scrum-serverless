"""Admin Gmail SMTP config: view, save, test-send."""
import datetime

from .mail import get_email_config, send_email
from .store import create_response, parse_body, table
from .templates import test_html


def route(path, method, event, params, user_claims):
    # GET /admin/config/email (Admin only)
    if path in ("/admin/config/email", "/admin/config/resend") and method == "GET":
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
        success, res = send_email(
            to_email, subject,
            test_html(cfg.get("gmail_user"), cfg.get("sender_name"), app_url, datetime.datetime.utcnow().isoformat()),
        )
        if success:
            return create_response(200, {"message": f"Email de prueba enviado exitosamente a {to_email}"})
        else:
            return create_response(400, {"error": f"Fallo al enviar correo con Gmail: {res}"})

    return None
