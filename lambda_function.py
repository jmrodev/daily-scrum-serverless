import json
import os
import re
import urllib.parse
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "DailyScrum")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def create_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def parse_body(event):
    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        import base64

        raw_body = base64.b64decode(raw_body).decode("utf-8")
    return json.loads(raw_body) if isinstance(raw_body, str) else raw_body


def handler(event, context):
    http_context = event.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET")
    raw_path = event.get("rawPath", "/")
    path = raw_path.rstrip("/")
    if not path:
        path = "/"

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS}

    params = event.get("queryStringParameters") or {}

    try:
        # =====================================================================
        # 1. PROJECTS CRUD
        # =====================================================================
        # GET /projects -> List all projects
        if path == "/projects" and method == "GET":
            resp = table.query(
                KeyConditionExpression=Key("PK").eq("META#PROJECTS")
            )
            projects = [
                {"name": item.get("name"), "created_at": item.get("created_at")}
                for item in resp.get("Items", [])
            ]
            return create_response(200, {"projects": projects})

        # POST /projects -> Create a project
        elif path == "/projects" and method == "POST":
            body = parse_body(event)
            name = (body.get("name") or "").strip()
            if not name:
                return create_response(400, {"error": "Project name is required"})

            item = {
                "PK": "META#PROJECTS",
                "SK": f"PROJECT#{name}",
                "name": name,
                "created_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": f"Project '{name}' created", "project": item})

        # DELETE /projects/{name} or DELETE /projects?name=...
        elif (re.match(r"^/projects/[^/]+$", path) or path == "/projects") and method == "DELETE":
            match = re.match(r"^/projects/([^/]+)$", path)
            name = urllib.parse.unquote(match.group(1)) if match else params.get("name")
            if not name:
                return create_response(400, {"error": "Project name is required"})

            table.delete_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"})
            return create_response(200, {"message": f"Project '{name}' deleted"})

        # =====================================================================
        # 2. MEMBERS CRUD
        # =====================================================================
        # GET /members?project=... or GET /projects/{project}/members
        member_list_match = re.match(r"^/projects/([^/]+)/members$", path)
        if (member_list_match or path == "/members") and method == "GET":
            project = (
                urllib.parse.unquote(member_list_match.group(1))
                if member_list_match
                else params.get("project")
            )
            if not project:
                return create_response(400, {"error": "Project name is required"})

            resp = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with("MEMBER#")
            )
            members = [
                {
                    "name": item.get("name"),
                    "project": project,
                    "role": item.get("role", "Developer"),
                }
                for item in resp.get("Items", [])
            ]
            return create_response(200, {"members": members})

        # POST /members or POST /projects/{project}/members -> Add member
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

            if not project or not name:
                return create_response(400, {"error": "Project and member name are required"})

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{name}",
                "name": name,
                "project": project,
                "role": role,
                "created_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": f"Member '{name}' added to '{project}'", "member": item})

        # DELETE /members or DELETE /projects/{project}/members/{name}
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

            table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"})
            return create_response(200, {"message": f"Member '{name}' removed from '{project}'"})

        # =====================================================================
        # 3. DAILY SCRUMS CRUD
        # =====================================================================
        # POST /scrums or POST / -> Record Daily
        if (path == "/scrums" or path == "/") and method == "POST":
            body = parse_body(event)
            project = body.get("project")
            week = body.get("week")
            day = body.get("day")
            member = body.get("member")
            answers = body.get("answers", [])

            if not all([project, week, day, member]):
                return create_response(400, {"error": "Missing fields: project, week, day, member"})

            table.put_item(
                Item={
                    "PK": f"PROJECT#{project}",
                    "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                    "project": project,
                    "week": week,
                    "day": day,
                    "member": member,
                    "answers": answers,
                    "updated_at": event.get("requestContext", {}).get("time", ""),
                }
            )
            return create_response(
                201,
                {
                    "message": f"Daily Scrum recorded for {member} ({week} - {day})",
                    "data": {"project": project, "week": week, "day": day, "member": member, "answers": answers},
                },
            )

        # GET /scrums or GET / -> Load Daily
        elif (path == "/scrums" or path == "/") and method == "GET":
            project = params.get("project")
            week = params.get("week")
            day = params.get("day")
            member = params.get("member")

            if not all([project, week, day, member]):
                return create_response(400, {"error": "Missing params: project, week, day, member"})

            response = table.get_item(
                Key={
                    "PK": f"PROJECT#{project}",
                    "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                }
            )
            item = response.get("Item")
            if not item:
                return create_response(404, {"error": "Daily Scrum not found"})

            return create_response(
                200,
                {
                    "message": f"Daily Scrum loaded for {member} ({week} - {day})",
                    "answers": item.get("answers", []),
                },
            )

        return create_response(404, {"error": f"Path '{path}' with method '{method}' not found"})

    except ClientError as err:
        return create_response(500, {"error": err.response["Error"]["Message"]})
    except Exception as err:
        return create_response(500, {"error": str(err)})
