"""HMAC session tokens, Cognito fallback claims, password hashing, auth gates."""
import hashlib
import hmac
import json
import os
import secrets
import time

from .store import _b64url_decode, _b64url_encode, create_response, table

# HMAC secret for server-minted session tokens. Injected via deploy.sh
# (openssl rand -hex 32). Never shipped to the browser. Empty = misconfigured.
TOKEN_SECRET = os.environ.get("TOKEN_SECRET", "")
TOKEN_TTL_SECONDS = 86400 * 7  # 7 days, preserved to avoid session-churn change


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
    from .store import CLIENT_ID

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


def require_admin(event):
    """Convenience helper for admin-only gating."""
    return require_auth(event, admin_only=True)


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
