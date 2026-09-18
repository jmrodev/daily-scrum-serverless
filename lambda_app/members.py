"""Members CRUD: admin-managed or self-assignment when the project allows it."""
import datetime
import re
import secrets
import time
import urllib.parse
from boto3.dynamodb.conditions import Attr, Key

from .activity import delete_user_account_completely
from .mail import get_email_config, send_email
from .store import _scan_all, create_response, parse_body, table
from .templates import invite_html
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

        # Look up member item first to obtain associated email
        mem_resp = table.get_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"})
        mem_item = mem_resp.get("Item") or {}
        member_email = (mem_item.get("email") or body.get("email") or params.get("email") or "").strip().lower()
        if not member_email:
            if "@" in name:
                member_email = name.strip().lower()
            else:
                scan_u = _scan_all(
                    FilterExpression=Key("PK").begins_with("USER#") & Attr("SK").eq("PROFILE") & Attr("name").eq(name)
                )
                if scan_u:
                    member_email = scan_u[0].get("email", "").strip().lower()

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
            # Self unassignment: only drop membership from this project
            table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"})
            return create_response(200, {"message": f"Member '{name}' removed from '{project}'"})

        # Admin deletion: check if admin is deleting their own account as sole admin
        if user_claims and user_claims.get("email") and member_email and member_email == user_claims.get("email").strip().lower():
            scan_admins = _scan_all(FilterExpression=Key("PK").begins_with("USER#") & Attr("SK").eq("PROFILE"))
            admin_count = 0
            for u in scan_admins:
                if "Admins" in (u.get("groups") or []) and u.get("email") != member_email:
                    admin_count += 1
            if admin_count == 0:
                return create_response(400, {"error": "No podés eliminar tu propia cuenta siendo el único administrador del sistema."})

        # Admin deletes member: purge account completely so re-adding starts from scratch
        delete_user_account_completely(member_email, project=project, member_name=name)
        return create_response(200, {"message": f"Member '{name}' and user account deleted completely."})

    return None
