"""User activity log + full account purge (cascades across projects)."""
import datetime
import time
import uuid
from boto3.dynamodb.conditions import Key

from .store import _query_all, _scan_all, cognito_idp, table
from .store import USER_POOL_ID


def log_user_activity(email, action, event=None):
    """Record user activity (LOGIN, SIGNUP, CONFIRM, OTP_VERIFY) in DynamoDB.
    Updates USER#{email} PROFILE (last_login, login_count) and logs to AUDIT#USER#{email}.
    """
    if not email:
        return
    email = email.strip().lower()
    now_iso = datetime.datetime.utcnow().isoformat()
    ip = ""
    ua = ""
    if event:
        http_ctx = event.get("requestContext", {}).get("http", {})
        ip = http_ctx.get("sourceIp") or event.get("requestContext", {}).get("identity", {}).get("sourceIp", "")
        headers = event.get("headers") or {}
        ua = headers.get("user-agent", "")

    # 1. Update USER#{email} PROFILE item
    try:
        table.update_item(
            Key={"PK": f"USER#{email}", "SK": "PROFILE"},
            UpdateExpression="SET last_login = :now, updated_at = :now ADD login_count :inc",
            ExpressionAttributeValues={":now": now_iso, ":inc": 1},
        )
    except Exception as e:
        print(f"Error updating user profile login count for {email}: {e}")

    # 2. Record chronological audit item
    try:
        event_id = str(uuid.uuid4())[:8]
        audit_item = {
            "PK": f"AUDIT#USER#{email}",
            "SK": f"EVENT#{now_iso}#{event_id}",
            "action": action,
            "email": email,
            "timestamp": now_iso,
            "ip": ip,
            "user_agent": ua[:160],
            "ttl": int(time.time()) + (86400 * 90),
        }
        table.put_item(Item=audit_item)
    except Exception as e:
        print(f"Error recording audit event for {email}: {e}")


def log_data_event(project, action, detail=None, actor=None):
    """Audit trail de datos: quién creó/modificó/borró qué dentro de un proyecto.

    Escribe en PK AUDIT#PROJECT#{project} con TTL 90 días. Liviano y best-effort:
    nunca rompe la operación principal si el log falla.
    """
    try:
        now_iso = datetime.datetime.utcnow().isoformat()
        event_id = str(uuid.uuid4())[:8]
        item = {
            "PK": f"AUDIT#PROJECT#{project}",
            "SK": f"EVENT#{now_iso}#{event_id}",
            "action": action,
            "project": project,
            "actor": (actor or "").strip().lower(),
            "timestamp": now_iso,
            "ttl": int(time.time()) + (86400 * 90),
        }
        if detail:
            item["detail"] = detail
        table.put_item(Item=item)
    except Exception as e:
        print(f"Error recording data audit event {action} for project {project}: {e}")


def delete_user_account_completely(email, project=None, member_name=None):
    """Purge a user account completely:
    1. USER#{email} PROFILE (password, status, tokens, codes)
    2. AUDIT#USER#{email} events
    3. AUTH#OTP EMAIL#{email}
    4. Cognito user pool account (if exists)
    5. PROJECT#{project} MEMBER#{member_name} (and any other MEMBER# with this email)
    6. Daily Scrums for this member in this project (or all projects)
    7. Unassign tasks assigned to this member
    """
    email = (email or "").strip().lower()

    # 1. Delete USER profile
    if email:
        try:
            table.delete_item(Key={"PK": f"USER#{email}", "SK": "PROFILE"})
        except Exception as e:
            print(f"Error deleting USER profile {email}: {e}")

        # 2. Delete all audit records for this user
        try:
            for item in _query_all(KeyConditionExpression=Key("PK").eq(f"AUDIT#USER#{email}")):
                table.delete_item(Key={"PK": item["PK"], "SK": item["SK"]})
        except Exception as e:
            print(f"Error deleting AUDIT records for {email}: {e}")

        # 3. Delete OTP items
        try:
            table.delete_item(Key={"PK": "AUTH#OTP", "SK": f"EMAIL#{email}"})
        except Exception as e:
            print(f"Error deleting OTP for {email}: {e}")

        # 4. Delete from Cognito User Pool
        if cognito_idp and USER_POOL_ID:
            try:
                cognito_idp.admin_delete_user(
                    UserPoolId=USER_POOL_ID,
                    Username=email,
                )
            except Exception as e:
                print(f"Cognito delete user ignored/error for {email}: {e}")

    # 5. Delete member item(s) from project(s)
    try:
        if project and member_name:
            table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{member_name}"})

        # Scan for any project MEMBER# items matching this email or member_name
        scan_expr = None
        expr_vals = {}
        attr_names = None
        if email and member_name:
            scan_expr = "begins_with(PK, :p) AND begins_with(SK, :m) AND (email = :em OR #n = :mn)"
            expr_vals = {":p": "PROJECT#", ":m": "MEMBER#", ":em": email, ":mn": member_name}
            attr_names = {"#n": "name"}
        elif email:
            scan_expr = "begins_with(PK, :p) AND begins_with(SK, :m) AND email = :em"
            expr_vals = {":p": "PROJECT#", ":m": "MEMBER#", ":em": email}
        elif member_name:
            scan_expr = "begins_with(PK, :p) AND SK = :sk"
            expr_vals = {":p": "PROJECT#", ":sk": f"MEMBER#{member_name}"}

        if scan_expr:
            kwargs = {
                "FilterExpression": scan_expr,
                "ExpressionAttributeValues": expr_vals,
            }
            if attr_names:
                kwargs["ExpressionAttributeNames"] = attr_names
            m_resp = _scan_all(**kwargs)
            for m_item in m_resp:
                table.delete_item(Key={"PK": m_item["PK"], "SK": m_item["SK"]})
    except Exception as e:
        print(f"Error purging MEMBER records for {email} / {member_name}: {e}")

    # 6. Delete Daily Scrums for this member
    try:
        del_names = set()
        if member_name:
            del_names.add(member_name.strip().lower())
        if email:
            del_names.add(email)
            del_names.add(email.split("@")[0].lower())

        if project:
            for s_item in _query_all(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}") & Key("SK").begins_with("WEEK#")
            ):
                s_mem = (s_item.get("member") or "").strip().lower()
                if s_mem in del_names:
                    table.delete_item(Key={"PK": s_item["PK"], "SK": s_item["SK"]})
        else:
            for s_item in _scan_all(
                FilterExpression="begins_with(PK, :p) AND begins_with(SK, :w)",
                ExpressionAttributeValues={":p": "PROJECT#", ":w": "WEEK#"},
            ):
                s_mem = (s_item.get("member") or "").strip().lower()
                if s_mem in del_names:
                    table.delete_item(Key={"PK": s_item["PK"], "SK": s_item["SK"]})
    except Exception as e:
        print(f"Error purging Daily Scrums for {email} / {member_name}: {e}")

    # 7. Unassign tasks assigned to this member
    try:
        del_names = set()
        if member_name:
            del_names.add(member_name.strip().lower())
        if email:
            del_names.add(email)
            del_names.add(email.split("@")[0].lower())

        if project:
            for t_item in _query_all(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}") & Key("SK").begins_with("TASK#")
            ):
                t_assignee = (t_item.get("assignee") or "").strip().lower()
                if t_assignee in del_names:
                    table.update_item(
                        Key={"PK": t_item["PK"], "SK": t_item["SK"]},
                        UpdateExpression="SET assignee = :unassigned",
                        ExpressionAttributeValues={":unassigned": ""},
                    )
        else:
            for t_item in _scan_all(
                FilterExpression="begins_with(PK, :p) AND begins_with(SK, :t)",
                ExpressionAttributeValues={":p": "PROJECT#", ":t": "TASK#"},
            ):
                t_assignee = (t_item.get("assignee") or "").strip().lower()
                if t_assignee in del_names:
                    table.update_item(
                        Key={"PK": t_item["PK"], "SK": t_item["SK"]},
                        UpdateExpression="SET assignee = :unassigned",
                        ExpressionAttributeValues={":unassigned": ""},
                    )
    except Exception as e:
        print(f"Error unassigning tasks for {email} / {member_name}: {e}")
