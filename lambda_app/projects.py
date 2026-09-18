"""Projects CRUD: rename migrates members+scrums+tasks, delete purges cascade."""
import datetime
import re
import time
import urllib.parse
from boto3.dynamodb.conditions import Key

from .activity import log_data_event
from .store import _query_all, create_response, parse_body, table
from .tokens import require_auth

TRASH_TTL_SECONDS = 86400 * 30  # 30 days in trash, auto-purged free via DynamoDB TTL


def _query_all_project(name):
    """All items of a project (members, scrums, tasks), paginated."""
    return _query_all(KeyConditionExpression=Key("PK").eq(f"PROJECT#{name}"))


def route(path, method, event, params, user_claims):
    # GET /projects (authenticated reads only)
    if path == "/projects" and method == "GET":
        _, err = require_auth(event)
        if err:
            return err
        resp = table.query(
            KeyConditionExpression=Key("PK").eq("META#PROJECTS"),
            FilterExpression="attribute_not_exists(#del)",
            ExpressionAttributeNames={"#del": "deleted"},
        )
        projects = [
            {
                "name": item.get("name"),
                "allow_self_assignment": bool(item.get("allow_self_assignment", False)),
                "created_at": item.get("created_at"),
            }
            for item in resp.get("Items", [])
        ]
        return create_response(200, {"projects": projects})

    # POST /projects (Admin only)
    elif path == "/projects" and method == "POST":
        _, err = require_auth(event, admin_only=True)
        if err:
            return err

        body = parse_body(event)
        name = (body.get("name") or "").strip()
        allow_self = bool(body.get("allow_self_assignment", False))
        if not name:
            return create_response(400, {"error": "Project name is required"})

        # Restore trashed project (META + all its items) instead of duplicating
        existing_meta = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"}).get("Item")
        if existing_meta and existing_meta.get("deleted"):
            table.update_item(
                Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"},
                UpdateExpression="SET allow_self_assignment = :a REMOVE deleted, deleted_at, #ttl",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={":a": allow_self},
            )
            restored = 0
            for it in _query_all_project(name):
                table.update_item(
                    Key={"PK": it["PK"], "SK": it["SK"]},
                    UpdateExpression="REMOVE deleted, deleted_at, #ttl",
                    ExpressionAttributeNames={"#ttl": "ttl"},
                )
                restored += 1
            log_data_event(name, "PROJECT_RESTORE", {"items": restored}, "")
            item = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"}).get("Item") or {}
            return create_response(200, {
                "message": f"Project '{name}' restored from trash",
                "project": item,
                "restored": True,
                "restored_items": restored,
            })

        item = {
            "PK": "META#PROJECTS",
            "SK": f"PROJECT#{name}",
            "name": name,
            "allow_self_assignment": allow_self,
            "created_at": event.get("requestContext", {}).get("time", ""),
        }
        table.put_item(Item=item)
        return create_response(201, {"message": f"Project '{name}' created", "project": item})

    # PUT /projects/{name} -> Rename project or toggle allow_self_assignment (Admin only)
    elif re.match(r"^/projects/[^/]+$", path) and method == "PUT":
        _, err = require_auth(event, admin_only=True)
        if err:
            return err

        old_name = urllib.parse.unquote(re.match(r"^/projects/([^/]+)$", path).group(1))
        body = parse_body(event)
        new_name = (body.get("newName") or old_name).strip()

        old_item_resp = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{old_name}"})
        old_item = old_item_resp.get("Item") or {}
        if old_item.get("deleted"):
            return create_response(404, {"error": f"Project '{old_name}' is in trash. Restore it first."})
        allow_self = bool(body.get("allow_self_assignment", old_item.get("allow_self_assignment", False)))

        if not new_name:
            return create_response(400, {"error": "New project name is required"})

        if old_name != new_name:
            # Evitar merge accidental: el destino no debe existir
            existing_new = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{new_name}"}).get("Item")
            if existing_new:
                return create_response(400, {"error": f"Project '{new_name}' already exists"})
            # Migrar todos los items vivos PROJECT#{old} -> PROJECT#{new} (la papelera no migra)
            last_key = None
            moved = 0
            while True:
                q_kwargs = {
                    "KeyConditionExpression": Key("PK").eq(f"PROJECT#{old_name}"),
                    "FilterExpression": "attribute_not_exists(#del)",
                    "ExpressionAttributeNames": {"#del": "deleted"},
                }
                if last_key:
                    q_kwargs["ExclusiveStartKey"] = last_key
                resp = table.query(**q_kwargs)
                for it in resp.get("Items", []):
                    new_item = dict(it)
                    new_item["PK"] = f"PROJECT#{new_name}"
                    if "project" in new_item:
                        new_item["project"] = new_name
                    table.put_item(Item=new_item)
                    table.delete_item(Key={"PK": it["PK"], "SK": it["SK"]})
                    moved += 1
                last_key = resp.get("LastEvaluatedKey")
                if not last_key:
                    break
            table.delete_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{old_name}"})

        item = {
            "PK": "META#PROJECTS",
            "SK": f"PROJECT#{new_name}",
            "name": new_name,
            "allow_self_assignment": allow_self,
            "created_at": old_item.get("created_at") or event.get("requestContext", {}).get("time", ""),
            "updated_at": event.get("requestContext", {}).get("time", ""),
        }
        table.put_item(Item=item)
        return create_response(
            200,
            {"message": f"Project '{new_name}' updated", "project": item},
        )

    # DELETE /projects/{name} (Admin only)
    elif (re.match(r"^/projects/[^/]+$", path) or path == "/projects") and method == "DELETE":
        _, err = require_auth(event, admin_only=True)
        if err:
            return err

        match = re.match(r"^/projects/([^/]+)$", path)
        name = urllib.parse.unquote(match.group(1)) if match else params.get("name")
        if not name:
            return create_response(400, {"error": "Project name is required"})

        # Soft cascade to trash: members + scrums + tasks get flags (restorable
        # 30d, auto-purged free via TTL). The META record goes to trash too.
        trashed = 0
        for it in _query_all_project(name):
            table.update_item(
                Key={"PK": it["PK"], "SK": it["SK"]},
                UpdateExpression="SET deleted = :t, deleted_at = :d, #ttl = :e",
                ExpressionAttributeNames={"#ttl": "ttl"},
                ExpressionAttributeValues={
                    ":t": True,
                    ":d": datetime.datetime.utcnow().isoformat(),
                    ":e": int(time.time()) + TRASH_TTL_SECONDS,
                },
            )
            trashed += 1
        table.update_item(
            Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"},
            UpdateExpression="SET deleted = :t, deleted_at = :d, #ttl = :e",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={
                ":t": True,
                ":d": datetime.datetime.utcnow().isoformat(),
                ":e": int(time.time()) + TRASH_TTL_SECONDS,
            },
        )
        log_data_event(name, "PROJECT_TRASH", {"items": trashed}, "")
        return create_response(200, {"message": f"Project '{name}' moved to trash", "trashed_items": trashed})

    return None
