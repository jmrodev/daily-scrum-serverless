"""Members CRUD: admin-managed or self-assignment when the project allows it."""
import datetime
import re
import secrets
import time
import urllib.parse
from boto3.dynamodb.conditions import Key

from .activity import log_data_event
from .activity import log_data_event
from .mail import get_email_config, send_email
from .store import create_response, parse_body, table
from .tokens import require_auth


def route(path, method, event, params, user_claims):
    # GET /projects/{project}/members
    member_list_match = re.match(r"^/projects/([^/]+)/members$", path)
    if (member_list_match or path == "/members") and method == "GET":
        _, err = require_auth(event)
        if err:
            return err
        project = (
            urllib.parse.unquote(member_list_match.group(1))
            if member_list_match
            else params.get("project")
        )
        if not project:
            return create_response(400, {"error": "Project name is required"})

        resp = table.query(
            KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
            & Key("SK").begins_with("MEMBER#"),
            FilterExpression="attribute_not_exists(#del)",
            ExpressionAttributeNames={"#del": "deleted"},
            ConsistentRead=True,
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

        # Restore trashed membership instead of re-inviting from scratch
        existing_member = table.get_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"}).get("Item")
        if existing_member and existing_member.get("deleted"):
            table.update_item(
                Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"},
                UpdateExpression="SET #n = :n, project = :p, #r = :r, email = :e, is_admin = :a, updated_at = :u REMOVE deleted, deleted_at, #ttl",
                ExpressionAttributeNames={"#n": "name", "#r": "role", "#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":n": name,
                    ":p": project,
                    ":r": role,
                    ":e": email,
                    ":a": is_admin,
                    ":u": datetime.datetime.utcnow().isoformat(),
                },
            )
            restored = table.get_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"}).get("Item") or {}
            account_missing = not table.get_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"}).get("Item")
            log_data_event(project, "MEMBER_RESTORE", {"member": name}, (user_claims.get("email") or "") if user_claims else "")
            return create_response(200, {
                "message": f"Member '{name}' restored to '{project}' from trash",
                "member": restored,
                "restored": True,
                "account_missing": account_missing,
            })

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
                sep = "&" if "?" in app_url else "?"
                activation_url = f"{app_url}{sep}action=activate&email={urllib.parse.quote(email)}&code={code}"
                role_badge = "Administrador" if is_admin else "Integrante"
                subject = f"Invitación a Daily Scrum ({project}) - Activá tu cuenta"
                sent, err_msg = send_email(
                    email, subject,
                    invite_html(name, project, role, role_badge, code, activation_url),
                )
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
            # Self unassignment: move membership to trash (restorable, account kept)
            table.update_item(
                Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"},
                UpdateExpression="SET deleted = :t, deleted_at = :d, #ttl = :e, updated_by = :u",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":t": True,
                    ":d": datetime.datetime.utcnow().isoformat(),
                    ":e": int(time.time()) + (86400 * 30),
                    ":u": (user_claims.get("email") or "").strip().lower(),
                },
            )
            return create_response(200, {"message": f"Member '{name}' moved to trash from '{project}' (restorable)"})

        # Admin removal: move membership to trash. The user account is NEVER
        # touched here — deleting work data must never kill drivers. Full
        # account purge lives only in DELETE /admin/users/{email}.
        table.update_item(
            Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"},
            UpdateExpression="SET deleted = :t, deleted_at = :d, #ttl = :e, updated_by = :u",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":t": True,
                ":d": datetime.datetime.utcnow().isoformat(),
                ":e": int(time.time()) + (86400 * 30),
                ":u": (user_claims.get("email") or "").strip().lower(),
            },
        )
        log_data_event(project, "MEMBER_TRASH", {"member": name}, (user_claims.get("email") or ""))
        return create_response(200, {"message": f"Member '{name}' moved to trash from '{project}' (account preserved)"})

    return None
