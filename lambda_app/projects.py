"""Projects CRUD: rename migrates members+scrums+tasks, delete purges cascade."""
import re
import urllib.parse
from boto3.dynamodb.conditions import Key

from .store import create_response, parse_body, table
from .tokens import require_auth


def route(path, method, event, params, user_claims):
    # GET /projects (authenticated reads only)
    if path == "/projects" and method == "GET":
        _, err = require_auth(event)
        if err:
            return err
        resp = table.query(KeyConditionExpression=Key("PK").eq("META#PROJECTS"))
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
        allow_self = bool(body.get("allow_self_assignment", old_item.get("allow_self_assignment", False)))

        if not new_name:
            return create_response(400, {"error": "New project name is required"})

        if old_name != new_name:
            # Evitar merge accidental: el destino no debe existir
            existing_new = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{new_name}"}).get("Item")
            if existing_new:
                return create_response(400, {"error": f"Project '{new_name}' already exists"})
            # Migrar todos los items PROJECT#{old} -> PROJECT#{new} (members, scrums, tasks)
            last_key = None
            moved = 0
            while True:
                q_kwargs = {"KeyConditionExpression": Key("PK").eq(f"PROJECT#{old_name}")}
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

        # Purga en cascada: members + scrums + tasks del proyecto
        purged = 0
        last_key = None
        while True:
            q_kwargs = {"KeyConditionExpression": Key("PK").eq(f"PROJECT#{name}")}
            if last_key:
                q_kwargs["ExclusiveStartKey"] = last_key
            resp = table.query(**q_kwargs)
            for it in resp.get("Items", []):
                table.delete_item(Key={"PK": it["PK"], "SK": it["SK"]})
                purged += 1
            last_key = resp.get("LastEvaluatedKey")
            if not last_key:
                break
        table.delete_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"})
        return create_response(200, {"message": f"Project '{name}' deleted", "purged_items": purged})

    return None
