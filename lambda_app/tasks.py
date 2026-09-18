"""Kanban tasks: list, create, update, delete (assignee must be a member)."""
import datetime
import uuid
from boto3.dynamodb.conditions import Key

from .activity import log_data_event
from .store import create_response, parse_body, table
from .tokens import require_auth


def route(path, method, event, params, user_claims):
    # GET /tasks -> Get all tasks for a project (authenticated reads only)
    if path == "/tasks" and method == "GET":
        _, err = require_auth(event)
        if err:
            return err
        project = params.get("project")
        if not project:
            return create_response(400, {"error": "Missing 'project' parameter"})

        response = table.query(
            KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
            & Key("SK").begins_with("TASK#"),
            ConsistentRead=True,
        )
        tasks = response.get("Items", [])
        return create_response(200, {"project": project, "tasks": tasks})

    # POST /tasks -> Create a task
    elif path == "/tasks" and method == "POST":
        _, err = require_auth(event)
        if err:
            return err
        body = parse_body(event)
        project = body.get("project")
        title = (body.get("title") or "").strip()
        assignee = (body.get("assignee") or "").strip()
        status = body.get("status") or "TODO"
        priority = body.get("priority") or "MEDIUM"
        blocker = (body.get("blocker") or "").strip()
        depends_on = body.get("depends_on") or []
        if isinstance(depends_on, str):
            depends_on = [depends_on] if depends_on else []
        blocked_by_task_id = (body.get("blocked_by_task_id") or "").strip()
        blocked_by_task_title = (body.get("blocked_by_task_title") or "").strip()

        if not project or not title:
            return create_response(400, {"error": "Missing 'project' or 'title'"})

        if assignee:
            mem_chk = table.get_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{assignee}"})
            if not mem_chk.get("Item"):
                return create_response(400, {"error": f"'{assignee}' no es un integrante asignado al proyecto '{project}'."})

        task_id = body.get("id") or str(uuid.uuid4())[:8]
        actor = (user_claims.get("email") or "").strip().lower()
        now_iso = datetime.datetime.utcnow().isoformat()
        item = {
            "PK": f"PROJECT#{project}",
            "SK": f"TASK#{task_id}",
            "id": task_id,
            "project": project,
            "title": title,
            "assignee": assignee,
            "status": status,
            "priority": priority,
            "blocker": blocker,
            "depends_on": depends_on,
            "blocked_by_task_id": blocked_by_task_id,
            "blocked_by_task_title": blocked_by_task_title,
            "created_by": actor,
            "created_at": now_iso,
            "updated_by": actor,
            "updated_at": now_iso,
        }
        table.put_item(Item=item)
        return create_response(201, {"message": "Task created successfully", "task": item})

    # PUT /tasks -> Update task status, assignee, title, or blocker
    elif path == "/tasks" and method == "PUT":
        _, err = require_auth(event)
        if err:
            return err
        body = parse_body(event)
        project = body.get("project")
        task_id = body.get("id")

        if not project or not task_id:
            return create_response(400, {"error": "Missing 'project' or 'id'"})

        new_assignee = body.get("assignee")
        if new_assignee and str(new_assignee).strip():
            mem_chk = table.get_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{str(new_assignee).strip()}"})
            if not mem_chk.get("Item"):
                return create_response(400, {"error": f"'{new_assignee}' no es un integrante asignado al proyecto '{project}'."})

        update_parts = ["updated_at = :up"]
        expr_names = {}
        expr_values = {":up": datetime.datetime.utcnow().isoformat()}

        if "status" in body:
            update_parts.append("#st = :st")
            expr_names["#st"] = "status"
            expr_values[":st"] = body["status"]

        if "assignee" in body:
            update_parts.append("assignee = :asgn")
            expr_values[":asgn"] = (body["assignee"] or "").strip()

        if "title" in body:
            update_parts.append("title = :ttl")
            expr_values[":ttl"] = body["title"]

        if "priority" in body:
            update_parts.append("priority = :prio")
            expr_values[":prio"] = body["priority"]

        if "blocker" in body:
            update_parts.append("blocker = :blk")
            expr_values[":blk"] = body["blocker"]

        if "depends_on" in body:
            deps = body["depends_on"]
            if isinstance(deps, str):
                deps = [deps] if deps else []
            update_parts.append("depends_on = :deps")
            expr_values[":deps"] = deps

        if "blocked_by_task_id" in body:
            update_parts.append("blocked_by_task_id = :bbtid")
            expr_values[":bbtid"] = body["blocked_by_task_id"]

        if "blocked_by_task_title" in body:
            update_parts.append("blocked_by_task_title = :bbttl")
            expr_values[":bbttl"] = body["blocked_by_task_title"]

        update_expr = "SET " + ", ".join(update_parts)
        expr_values[":upd_by"] = (user_claims.get("email") or "").strip().lower()
        update_parts.append("updated_by = :upd_by")
        update_expr = "SET " + ", ".join(update_parts)
        kwargs = {
            "Key": {"PK": f"PROJECT#{project}", "SK": f"TASK#{task_id}"},
            "UpdateExpression": update_expr,
            "ExpressionAttributeValues": expr_values,
        }
        if expr_names:
            kwargs["ExpressionAttributeNames"] = expr_names

        table.update_item(**kwargs)
        return create_response(200, {"message": "Task updated successfully"})

    # DELETE /tasks -> Delete a task
    elif path == "/tasks" and method == "DELETE":
        _, err = require_auth(event)
        if err:
            return err
        body = parse_body(event) if event.get("body") else {}
        project = params.get("project") or body.get("project")
        task_id = params.get("id") or body.get("id")

        if not project or not task_id:
            return create_response(400, {"error": "Missing 'project' or 'id'"})

        table.delete_item(
            Key={"PK": f"PROJECT#{project}", "SK": f"TASK#{task_id}"}
        )
        return create_response(200, {"message": "Task deleted successfully"})

    return None
