"""Admin user accounts: activity audit, list, purge (sole-admin protected)."""
import datetime
import re
import urllib.parse
from boto3.dynamodb.conditions import Attr, Key

from .activity import delete_user_account_completely
from .store import _scan_all, create_response, parse_body, table
from .tokens import require_admin


def route(path, method, event, params, user_claims):
    # GET /admin/audit/activity (Admin only) -> Member login & signup activity metrics
    if path == "/admin/audit/activity" and method == "GET":
        if not user_claims or not user_claims.get("is_admin"):
            return create_response(403, {"error": "Forbidden: Solo administradores pueden ver la auditoría de actividad."})

        project = params.get("project")
        member_emails = set()
        member_details = {}

        if project:
            resp = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with("MEMBER#"),
                FilterExpression="attribute_not_exists(#del)",
                ExpressionAttributeNames={"#del": "deleted"},
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
            for item in _scan_all(
                FilterExpression=Key("PK").begins_with("USER#") & Key("SK").eq("PROFILE")
            ):
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
            # Only set last_login if user has actually logged in or has audit events
            actual_last_login = p_item.get("last_login") or (events[0]["timestamp"] if events else "")

            # Accurately compute login count (never default to 1 for invited users)
            if p_item.get("login_count") is not None:
                login_count = int(p_item.get("login_count"))
            elif events:
                login_count = len(events)
            else:
                login_count = 0

            status = p_item.get("status") or ("CONFIRMED" if p_item.get("password_hash") else "INVITED")
            info = member_details.get(em, {})

            activity_records.append({
                "email": em,
                "name": p_item.get("name") or info.get("name") or em.split("@")[0],
                "role": info.get("role") or "Developer",
                "is_admin": bool(info.get("is_admin", False) or "Admins" in (p_item.get("groups") or [])),
                "status": status,
                "created_at": created_at,
                "last_login": actual_last_login,
                "login_count": login_count,
                "events": events,
            })

        return create_response(200, {
            "project": project or "ALL",
            "activity": activity_records,
            "server_time": datetime.datetime.utcnow().isoformat(),
        })

    # GET /admin/users (Admin only) -> List all registered user accounts
    elif path == "/admin/users" and method == "GET":
        _, err = require_admin(event)
        if err:
            return err
        scan_users = _scan_all(FilterExpression=Key("PK").begins_with("USER#") & Attr("SK").eq("PROFILE"))
        user_list = []
        for u in scan_users:
            groups = u.get("groups") or []
            user_list.append({
                "email": u.get("email"),
                "name": u.get("name") or (u.get("email") or "").split("@")[0],
                "status": u.get("status", "CONFIRMED"),
                "is_admin": "Admins" in groups,
                "created_at": u.get("created_at"),
                "last_login": u.get("last_login"),
            })
        user_list.sort(key=lambda x: (x.get("name") or "").lower())
        return create_response(200, {"users": user_list})

    # DELETE /admin/users/{email} (Admin only) -> Purge user account and start from scratch
    user_del_match = re.match(r"^/admin/users/([^/]+)$", path)
    if (user_del_match or path == "/admin/users") and method == "DELETE":
        _, err = require_admin(event)
        if err:
            return err
        del_email = urllib.parse.unquote(user_del_match.group(1)) if user_del_match else (params.get("email") or parse_body(event).get("email") or "")
        del_email = del_email.strip().lower()
        if not del_email:
            return create_response(400, {"error": "Email is required"})

        # Prevent deleting only remaining admin
        if user_claims and user_claims.get("email") and del_email == user_claims.get("email").strip().lower():
            scan_admins = _scan_all(FilterExpression=Key("PK").begins_with("USER#") & Attr("SK").eq("PROFILE"))
            admin_count = 0
            for u in scan_admins:
                if "Admins" in (u.get("groups") or []) and u.get("email") != del_email:
                    admin_count += 1
            if admin_count == 0:
                return create_response(400, {"error": "No podés eliminar tu propia cuenta siendo el único administrador del sistema."})

        delete_user_account_completely(del_email)
        return create_response(200, {"message": f"User account '{del_email}' deleted completely."})

    return None
