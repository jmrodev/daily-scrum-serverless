"""POST /auth/confirm — verify code / activate invited user, mint session."""
import datetime
import time
import uuid

from .activity import log_user_activity
from .store import create_response, parse_body, table
from .tokens import TOKEN_TTL_SECONDS, get_user_groups, hash_password, mint_token


def route(path, method, event, params, user_claims):
    # POST /auth/confirm -> Confirm user registration code or activate invited user
    if path == "/auth/confirm" and method == "POST":
        body = parse_body(event)
        email = (body.get("email") or "").strip().lower()
        code = (body.get("code") or "").strip()
        password = body.get("password") or ""
        print(f"[AUTH CONFIRM] Attempt for email='{email}', code='{code}'")

        if not email or not code:
            return create_response(400, {"error": "Email y código de verificación son requeridos"})

        user_resp = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
        user_item = user_resp.get("Item")
        if not user_item:
            print(f"[AUTH CONFIRM] User not found: {email}")
            return create_response(404, {"error": "Usuario no encontrado"})

        # Check verification code & expiry
        stored_code = str(user_item.get("verification_code") or "").strip()
        norm_code = code.replace(" ", "").replace("-", "")
        norm_stored = stored_code.replace(" ", "").replace("-", "")
        code_ttl = int(user_item.get("code_ttl") or 0)
        now = int(time.time())

        print(f"[AUTH CONFIRM] Verification check: email='{email}', received='{code}', stored='{stored_code}', match={norm_code == norm_stored}, now={now}, ttl={code_ttl}")

        if not stored_code or norm_code != norm_stored:
            print(f"[AUTH CONFIRM] Code mismatch: received='{norm_code}', stored='{norm_stored}'")
            return create_response(400, {"error": "Código de verificación incorrecto"})

        if code_ttl and now > code_ttl:
            print(f"[AUTH CONFIRM] Code expired: now={now} > ttl={code_ttl}")
            return create_response(400, {"error": "El código de verificación ha expirado. Solicitá uno nuevo registrándote de nuevo."})

        # If user was invited (FORCE_CHANGE_PASSWORD) or registering, update status and set password
        set_clauses = ["#st = :status", "updated_at = :up"]
        expr_names = {"#st": "status"}
        expr_values = {
            ":status": "CONFIRMED",
            ":up": datetime.datetime.utcnow().isoformat(),
        }

        if password:
            if len(password) < 8:
                return create_response(400, {"error": "La contraseña debe tener al menos 8 caracteres"})
            set_clauses.append("password_hash = :ph")
            expr_values[":ph"] = hash_password(password)

        update_expr = f"SET {', '.join(set_clauses)} REMOVE verification_code, code_ttl"

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

    return None
