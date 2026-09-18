"""POST /auth/login + GET /auth/me."""
import time
import uuid
from botocore.exceptions import ClientError

from .activity import log_user_activity
from .store import CLIENT_ID, cognito_idp, create_response, parse_body, table
from .tokens import TOKEN_TTL_SECONDS, extract_user_claims, get_user_groups, mint_token, verify_password


def route(path, method, event, params, user_claims):
    # POST /auth/login -> Standard login with Email + Password
    if path == "/auth/login" and method == "POST":
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

    return None
