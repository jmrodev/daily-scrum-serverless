"""POST /auth/identify — email-first routing for the stepped auth gate.

Public endpoint (needed pre-auth): given an email, tells the frontend which
step to show — login (confirmed), confirm (pending/invited), or signup
(unknown). Throttled 10/min per source IP to blunt address enumeration;
single get_item cost on every path keeps timing uniform.
"""
import time

from .store import create_response, parse_body, table

IDENTIFY_LIMIT_PER_MINUTE = 10


def _source_ip(event):
    http_ctx = event.get("requestContext", {}).get("http", {})
    return http_ctx.get("sourceIp") or event.get("requestContext", {}).get("identity", {}).get("sourceIp", "")


def _throttled(ip):
    """Fixed-window 10/min per IP, counters auto-expire via TTL (free)."""
    if not ip:
        return False
    now = int(time.time())
    window = now // 60
    key = {"PK": "RATE#IDENTIFY", "SK": f"IP#{ip}"}
    stored = table.get_item(Key=key).get("Item") or {}
    if stored.get("window") == window and int(stored.get("count", 0)) >= IDENTIFY_LIMIT_PER_MINUTE:
        return True
    table.put_item(Item={
        "PK": key["PK"],
        "SK": key["SK"],
        "window": window,
        "count": int(stored.get("count", 0)) + 1 if stored.get("window") == window else 1,
        "ttl": now + 120,
    })
    return False


def route(path, method, event, params, user_claims):
    # POST /auth/identify -> Which auth step for this email?
    if path == "/auth/identify" and method == "POST":
        if _throttled(_source_ip(event)):
            return create_response(429, {"error": "Demasiadas verificaciones. Esperá un minuto."})
        body = parse_body(event)
        email = (body.get("email") or "").strip().lower()
        if not email or "@" not in email:
            return create_response(400, {"error": "Email válido es requerido"})

        user = table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"}).get("Item")
        if not user:
            return create_response(200, {"status": "signup", "email": email})

        status = user.get("status") or ""
        name = user.get("name") or email.split("@")[0]
        if status in ("PENDING_VERIFICATION", "FORCE_CHANGE_PASSWORD") or not user.get("password_hash"):
            return create_response(200, {"status": "confirm", "email": email, "name": name})

        return create_response(200, {"status": "login", "email": email, "name": name})

    return None
