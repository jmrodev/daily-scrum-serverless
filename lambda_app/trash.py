"""Trash (papelera): list trashed items per project, restore, purge forever.

All reads/writes here are admin-only. Soft-deleted items carry
deleted=true + ttl (30d, auto-purged free via DynamoDB TTL).
"""
from boto3.dynamodb.conditions import Key

from .activity import log_data_event
from .store import _query_all, create_response, parse_body, table
from .tokens import require_admin


def _trash_items(project):
    return _query_all(
        KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}"),
        FilterExpression="#del = :t",
        ExpressionAttributeNames={"#del": "deleted"},
        ExpressionAttributeValues={":t": True},
    )


def route(path, method, event, params, user_claims):
    # GET /admin/trash?project=X -> List trashed items of a project
    if path == "/admin/trash" and method == "GET":
        _, err = require_admin(event)
        if err:
            return err
        project = params.get("project")
        if not project:
            return create_response(400, {"error": "Project parameter is required"})

        items = _trash_items(project)
        trash = [
            {
                "pk": it.get("PK"),
                "sk": it.get("SK"),
                "kind": "member" if it.get("SK", "").startswith("MEMBER#")
                else "task" if it.get("SK", "").startswith("TASK#")
                else "scrum" if it.get("SK", "").startswith("WEEK#") else "other",
                "title": it.get("title") or it.get("name") or it.get("member") or it.get("SK"),
                "deleted_at": it.get("deleted_at"),
            }
            for it in items
        ]
        return create_response(200, {"project": project, "count": len(trash), "trash": trash})

    # POST /admin/trash/restore -> Restore one trashed item {project, pk, sk}
    if path == "/admin/trash/restore" and method == "POST":
        _, err = require_admin(event)
        if err:
            return err
        body = parse_body(event)
        project = body.get("project")
        pk = body.get("pk")
        sk = body.get("sk")

        if not project or not pk or not sk:
            return create_response(400, {"error": "Missing params: project, pk, sk"})
        if pk != f"PROJECT#{project}":
            return create_response(400, {"error": "pk does not belong to project"})

        existing = table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
        if not existing or not existing.get("deleted"):
            return create_response(404, {"error": "No trashed item found with those keys"})

        table.update_item(
            Key={"PK": pk, "SK": sk},
            UpdateExpression="REMOVE deleted, deleted_at, #ttl",
            ExpressionAttributeNames={"#ttl": "ttl"},
        )
        log_data_event(project, "TRASH_RESTORE", {"sk": sk}, (user_claims.get("email") or "") if user_claims else "")
        return create_response(200, {"message": "Item restored from trash"})

    # DELETE /admin/trash -> Purge one trashed item forever {project, pk, sk}
    if path == "/admin/trash" and method == "DELETE":
        _, err = require_admin(event)
        if err:
            return err
        body = parse_body(event) if event.get("body") else {}
        project = params.get("project") or body.get("project")
        pk = params.get("pk") or body.get("pk")
        sk = params.get("sk") or body.get("sk")

        if not project or not pk or not sk:
            return create_response(400, {"error": "Missing params: project, pk, sk"})
        if pk != f"PROJECT#{project}":
            return create_response(400, {"error": "pk does not belong to project"})

        existing = table.get_item(Key={"PK": pk, "SK": sk}).get("Item")
        if not existing or not existing.get("deleted"):
            return create_response(404, {"error": "No trashed item found with those keys (only trash can be purged)"})

        table.delete_item(Key={"PK": pk, "SK": sk})
        log_data_event(project, "TRASH_PURGE", {"sk": sk}, (user_claims.get("email") or "") if user_claims else "")
        return create_response(200, {"message": "Item purged forever"})

    return None
