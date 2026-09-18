"""Daily scrums: weekly matrix + single daily, self-scoped for members."""
import datetime
import re
import time
from boto3.dynamodb.conditions import Key

from .activity import log_data_event
from .store import create_response, parse_body, table
from .tokens import require_auth

_DAY_ALIASES = {
    "lunes": "Lunes",
    "martes": "Martes",
    "miercoles": "Miércoles",
    "miércoles": "Miércoles",
    "jueves": "Jueves",
    "viernes": "Viernes",
    "sabado": "Sábado",
    "sábado": "Sábado",
    "domingo": "Domingo",
}


def _norm_day(day):
    """Canónico de día con tilde. Migra variantes viejas sin tilde al leer/escribir."""
    if day is None:
        return day
    return _DAY_ALIASES.get(str(day).strip().lower(), str(day).strip())


def route(path, method, event, params, user_claims):
    # POST /scrums or PUT /scrums -> Record / Update Daily Scrum
    if (path == "/scrums" or path == "/") and method in ["POST", "PUT"]:
        _, err = require_auth(event)
        if err:
            return err
        body = parse_body(event)
        project = body.get("project")
        week = body.get("week")
        day = _norm_day(body.get("day"))
        member = body.get("member")
        answers = body.get("answers", [])

        if not all([project, week, day, member]):
            return create_response(400, {"error": "Missing fields: project, week, day, member"})

        # RBAC: Non-admin users can ONLY create or modify scrums for themselves
        if user_claims and not user_claims["is_admin"]:
            user_name = (user_claims.get("name") or "").strip().lower()
            user_email = (user_claims.get("email") or "").strip().lower()
            target_norm = member.strip().lower()

            if (
                target_norm != user_name
                and target_norm != user_email
                and target_norm != user_email.split("@")[0]
            ):
                return create_response(
                    403,
                    {
                        "error": f"Forbidden: You can only record or modify your own Daily Scrum (logged in as {user_claims.get('name')})."
                    },
                )

        blocking_task_id = (body.get("blocking_task_id") or "").strip()
        blocking_task_title = (body.get("blocking_task_title") or "").strip()

        actor = (user_claims.get("email") or "").strip().lower()
        item = {
            "PK": f"PROJECT#{project}",
            "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
            "project": project,
            "week": week,
            "day": day,
            "member": member,
            "answers": answers,
            "blocking_task_id": blocking_task_id,
            "blocking_task_title": blocking_task_title,
            "updated_by": actor,
            "updated_at": event.get("requestContext", {}).get("time", "") or datetime.datetime.utcnow().isoformat(),
        }
        if method == "POST":
            item["created_by"] = actor
            item["created_at"] = item["updated_at"]
        if "kanban_refs" in body:
            # Caller tracks kanban snapshot explicitly (sync flow)
            item["kanban_refs"] = body.get("kanban_refs") or []
        else:
            # Manual saves preserve the existing snapshot so tracking survives edits
            prev = table.get_item(Key={"PK": item["PK"], "SK": item["SK"]}).get("Item") or {}
            if prev.get("kanban_refs"):
                item["kanban_refs"] = prev["kanban_refs"]
        table.put_item(Item=item)
        return create_response(
            200 if method == "PUT" else 201,
            {
                "message": f"Daily Scrum recorded for {member} ({week} - {day})",
                "data": item,
            },
        )

    # GET /scrums -> Full Weekly Matrix or Single Item (authenticated reads only)
    elif (path == "/scrums" or path == "/") and method == "GET":
        _, err = require_auth(event)
        if err:
            return err
        project = params.get("project")
        week = params.get("week")
        day = _norm_day(params.get("day"))
        member = params.get("member")

        if not project:
            return create_response(400, {"error": "Project parameter is required"})

        # Case A: Get all distinct weeks for a project (when week is omitted)
        if not week:
            resp = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with("WEEK#"),
                FilterExpression="attribute_not_exists(#del)",
                ProjectionExpression="#w",
                ExpressionAttributeNames={"#w": "week", "#del": "deleted"},
                ConsistentRead=True,
            )
            items = resp.get("Items", [])
            weeks = list({item.get("week") for item in items if item.get("week")})

            def week_key(w):
                try:
                    nums = re.findall(r"\d+", w)
                    return int(nums[0]) if nums else 0
                except Exception:
                    return 0
            weeks.sort(key=week_key)
            return create_response(200, {"project": project, "weeks": weeks})

        # Case B: Get full weekly matrix for a project
        if week and not (day and member):
            resp = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with(f"WEEK#{week}#"),
                FilterExpression="attribute_not_exists(#del)",
                ExpressionAttributeNames={"#del": "deleted"},
                ConsistentRead=True,
            )
            items = resp.get("Items", [])
            return create_response(
                200,
                {
                    "project": project,
                    "week": week,
                    "count": len(items),
                    "scrums": items,
                },
            )

        # Case B: Get single member daily
        if not all([project, week, day, member]):
            return create_response(400, {"error": "Missing params: project, week, day, member"})

        response = table.get_item(
            Key={
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
            }
        )
        item = response.get("Item")
        if not item or item.get("deleted"):
            return create_response(404, {"error": "Daily Scrum not found"})

        return create_response(
            200,
            {
                "message": f"Daily Scrum loaded for {member} ({week} - {day})",
                "answers": item.get("answers", []),
                "data": item,
            },
        )

    # DELETE /scrums -> Move a Daily Scrum entry to trash (soft-delete, restorable 30d)
    elif (path == "/scrums" or path == "/") and method == "DELETE":
        _, err = require_auth(event)
        if err:
            return err
        body = parse_body(event) if event.get("body") else {}
        project = params.get("project") or body.get("project")
        week = params.get("week") or body.get("week")
        day = _norm_day(params.get("day") or body.get("day"))
        member = params.get("member") or body.get("member")

        if not all([project, week, day, member]):
            return create_response(400, {"error": "Missing params: project, week, day, member"})

        # RBAC: Non-admin users can ONLY delete their own scrums
        if user_claims and not user_claims["is_admin"]:
            user_name = (user_claims.get("name") or "").strip().lower()
            user_email = (user_claims.get("email") or "").strip().lower()
            target_norm = member.strip().lower()

            if (
                target_norm != user_name
                and target_norm != user_email
                and target_norm != user_email.split("@")[0]
            ):
                return create_response(
                    403,
                    {
                        "error": f"Forbidden: You can only delete your own Daily Scrum (logged in as {user_claims.get('name')})."
                    },
                )

        table.update_item(
            Key={
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
            },
            UpdateExpression="SET deleted = :t, deleted_at = :d, #ttl = :e, updated_by = :u",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":t": True,
                ":d": datetime.datetime.utcnow().isoformat(),
                ":e": int(time.time()) + (86400 * 30),
                ":u": (user_claims.get("email") or "").strip().lower(),
            },
        )
        log_data_event(
            project, "SCRUM_TRASH",
            {"member": member, "week": week, "day": day},
            (user_claims.get("email") or ""),
        )
        return create_response(
            200,
            {"message": f"Daily Scrum moved to trash for {member} ({week} - {day})"},
        )

    # POST /scrums/restore -> Restore a trashed Daily Scrum entry
    elif path == "/scrums/restore" and method == "POST":
        _, err = require_auth(event)
        if err:
            return err
        body = parse_body(event)
        project = body.get("project")
        week = body.get("week")
        day = _norm_day(body.get("day"))
        member = body.get("member")

        if not all([project, week, day, member]):
            return create_response(400, {"error": "Missing params: project, week, day, member"})

        existing = table.get_item(
            Key={
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
            }
        ).get("Item")
        if not existing or not existing.get("deleted"):
            return create_response(404, {"error": "No trashed Daily Scrum found with those params"})

        table.update_item(
            Key={
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
            },
            UpdateExpression="REMOVE deleted, deleted_at, #ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
        )
        log_data_event(
            project, "SCRUM_RESTORE",
            {"member": member, "week": week, "day": day},
            (user_claims.get("email") or ""),
        )
        return create_response(200, {"message": "Daily Scrum restored from trash"})

    return None
