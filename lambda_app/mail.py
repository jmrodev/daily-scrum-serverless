"""Gmail SMTP configuration + sending (stdlib only, no external deps)."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from .store import table


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
