import base64
import datetime
import json
import os
import re
import time
import urllib.parse
import uuid
import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "DailyScrum")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
cognito_idp = boto3.client("cognito-idp")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
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
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    return json.loads(raw_body) if isinstance(raw_body, str) else raw_body


def extract_user_claims(event):
    """Extract and validate user claims from the Authorization: Bearer <token> header.
    Decodes the JWT payload safely without external dependencies.
    """
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:].strip()
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        payload_b64 = parts[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        claims = json.loads(payload_bytes.decode("utf-8"))

        exp = claims.get("exp")
        if exp and exp < time.time():
            return None

        email = (
            claims.get("email")
            or claims.get("cognito:username")
            or claims.get("username")
            or ""
        )
        name = claims.get("name") or claims.get("custom:name") or email.split("@")[0]
        groups = claims.get("cognito:groups") or []
        if isinstance(groups, str):
            groups = [groups]

        is_admin = "Admins" in groups

        return {
            "email": email,
            "name": name,
            "groups": groups,
            "is_admin": is_admin,
            "sub": claims.get("sub", ""),
        }
    except Exception:
        return None


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
    user_claims = extract_user_claims(event)

    try:
        # =====================================================================
        # 1. AUTH ENDPOINTS (Cognito Integration)
        # =====================================================================
        # POST /auth/signup
        if path == "/auth/signup" and method == "POST":
            if not CLIENT_ID:
                return create_response(500, {"error": "Cognito CLIENT_ID is not configured"})
            body = parse_body(event)
            email = (body.get("email") or "").strip()
            password = body.get("password") or ""
            name = (body.get("name") or email.split("@")[0]).strip()

            if not email or not password:
                return create_response(400, {"error": "Email and password are required"})

            try:
                res = cognito_idp.sign_up(
                    ClientId=CLIENT_ID,
                    Username=email,
                    Password=password,
                    UserAttributes=[
                        {"Name": "email", "Value": email},
                        {"Name": "name", "Value": name},
                    ],
                )
                return create_response(
                    201,
                    {
                        "message": "User registered successfully. Check your email for the confirmation code.",
                        "userSub": res.get("UserSub"),
                        "email": email,
                        "name": name,
                    },
                )
            except ClientError as e:
                code = e.response["Error"]["Code"]
                msg = e.response["Error"]["Message"]
                return create_response(400, {"error": msg, "code": code})

        # POST /auth/confirm
        elif path == "/auth/confirm" and method == "POST":
            if not CLIENT_ID:
                return create_response(500, {"error": "Cognito CLIENT_ID is not configured"})
            body = parse_body(event)
            email = (body.get("email") or "").strip()
            code = (body.get("code") or "").strip()

            if not email or not code:
                return create_response(400, {"error": "Email and confirmation code are required"})

            try:
                cognito_idp.confirm_sign_up(
                    ClientId=CLIENT_ID,
                    Username=email,
                    ConfirmationCode=code,
                )
                # Automatically assign confirmed user to the 'Members' group
                if USER_POOL_ID:
                    try:
                        cognito_idp.admin_add_user_to_group(
                            UserPoolId=USER_POOL_ID,
                            Username=email,
                            GroupName="Members",
                        )
                    except Exception:
                        pass

                return create_response(200, {"message": "Account verified! You can now log in."})
            except ClientError as e:
                return create_response(400, {"error": e.response["Error"]["Message"]})

        # POST /auth/login
        elif path == "/auth/login" and method == "POST":
            if not CLIENT_ID:
                return create_response(500, {"error": "Cognito CLIENT_ID is not configured"})
            body = parse_body(event)
            email = (body.get("email") or "").strip()
            password = body.get("password") or ""

            if not email or not password:
                return create_response(400, {"error": "Email and password are required"})

            try:
                auth_resp = cognito_idp.initiate_auth(
                    ClientId=CLIENT_ID,
                    AuthFlow="USER_PASSWORD_AUTH",
                    AuthParameters={"USERNAME": email, "PASSWORD": password},
                )
                auth_result = auth_resp.get("AuthenticationResult", {})
                id_token = auth_result.get("IdToken")
                access_token = auth_result.get("AccessToken")
                refresh_token = auth_result.get("RefreshToken")

                # Parse claims from IdToken
                dummy_event = {"headers": {"authorization": f"Bearer {id_token}"}}
                claims = extract_user_claims(dummy_event) or {
                    "email": email,
                    "name": email.split("@")[0],
                    "groups": [],
                    "is_admin": False,
                }

                return create_response(
                    200,
                    {
                        "message": "Login successful",
                        "idToken": id_token,
                        "accessToken": access_token,
                        "refreshToken": refresh_token,
                        "user": claims,
                    },
                )
            except ClientError as e:
                return create_response(401, {"error": e.response["Error"]["Message"]})

        # GET /auth/me
        elif path == "/auth/me" and method == "GET":
            if not user_claims:
                return create_response(401, {"error": "Unauthorized or session expired"})
            return create_response(200, {"user": user_claims})

        # =====================================================================
        # 2. PROJECTS CRUD (Admin-Gated Modification)
        # =====================================================================
        # GET /projects
        if path == "/projects" and method == "GET":
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

        # POST /projects (Admin only when auth is active)
        elif path == "/projects" and method == "POST":
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can create projects."},
                )

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
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can rename projects."},
                )

            old_name = urllib.parse.unquote(re.match(r"^/projects/([^/]+)$", path).group(1))
            body = parse_body(event)
            new_name = (body.get("newName") or old_name).strip()

            old_item_resp = table.get_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{old_name}"})
            old_item = old_item_resp.get("Item") or {}
            allow_self = bool(body.get("allow_self_assignment", old_item.get("allow_self_assignment", False)))

            if not new_name:
                return create_response(400, {"error": "New project name is required"})

            if old_name != new_name:
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
            if user_claims and not user_claims["is_admin"]:
                return create_response(
                    403,
                    {"error": "Forbidden: Only administrators can delete projects."},
                )

            match = re.match(r"^/projects/([^/]+)$", path)
            name = urllib.parse.unquote(match.group(1)) if match else params.get("name")
            if not name:
                return create_response(400, {"error": "Project name is required"})

            table.delete_item(Key={"PK": "META#PROJECTS", "SK": f"PROJECT#{name}"})
            return create_response(200, {"message": f"Project '{name}' deleted"})

        # =====================================================================
        # 3. MEMBERS CRUD (Admin-Gated or Self-Assignment when enabled)
        # =====================================================================
        # GET /projects/{project}/members
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
                    "email": item.get("email", ""),
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
            email = (body.get("email") or "").strip()

            if not project or not name:
                return create_response(400, {"error": "Project and member name are required"})

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

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{name}",
                "name": name,
                "project": project,
                "role": role,
                "email": email,
                "created_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": f"Member '{name}' added to '{project}'", "member": item})

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
            email = (body.get("email") or "").strip()

            if old_name != new_name:
                table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{old_name}"})

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"MEMBER#{new_name}",
                "name": new_name,
                "project": project,
                "role": role,
                "email": email,
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

            table.delete_item(Key={"PK": f"PROJECT#{project}", "SK": f"MEMBER#{name}"})
            return create_response(200, {"message": f"Member '{name}' removed from '{project}'"})

        # =====================================================================
        # 4. DAILY SCRUMS CRUD (Member Self-Protection + Admin Access)
        # =====================================================================
        # POST /scrums or PUT /scrums -> Record / Update Daily Scrum
        if (path == "/scrums" or path == "/") and method in ["POST", "PUT"]:
            body = parse_body(event)
            project = body.get("project")
            week = body.get("week")
            day = body.get("day")
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

            item = {
                "PK": f"PROJECT#{project}",
                "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                "project": project,
                "week": week,
                "day": day,
                "member": member,
                "answers": answers,
                "updated_at": event.get("requestContext", {}).get("time", ""),
            }
            table.put_item(Item=item)
            return create_response(
                200 if method == "PUT" else 201,
                {
                    "message": f"Daily Scrum recorded for {member} ({week} - {day})",
                    "data": item,
                },
            )

        # GET /scrums -> Full Weekly Matrix or Single Item (Transparent to all)
        elif (path == "/scrums" or path == "/") and method == "GET":
            project = params.get("project")
            week = params.get("week")
            day = params.get("day")
            member = params.get("member")

            if not project:
                return create_response(400, {"error": "Project parameter is required"})

            # Case A: Get full weekly matrix for a project
            if week and not (day and member):
                resp = table.query(
                    KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                    & Key("SK").begins_with(f"WEEK#{week}#")
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
            if not item:
                return create_response(404, {"error": "Daily Scrum not found"})

            return create_response(
                200,
                {
                    "message": f"Daily Scrum loaded for {member} ({week} - {day})",
                    "answers": item.get("answers", []),
                    "data": item,
                },
            )

        # DELETE /scrums -> Delete a Daily Scrum entry
        elif (path == "/scrums" or path == "/") and method == "DELETE":
            body = parse_body(event) if event.get("body") else {}
            project = params.get("project") or body.get("project")
            week = params.get("week") or body.get("week")
            day = params.get("day") or body.get("day")
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

            table.delete_item(
                Key={
                    "PK": f"PROJECT#{project}",
                    "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                }
            )
            return create_response(
                200,
                {"message": f"Daily Scrum deleted for {member} ({week} - {day})"},
            )

        # =====================================================================
        # 5. KANBAN TASK ENDPOINTS (Work in Progress / Scrumban)
        # =====================================================================
        # GET /tasks -> Get all tasks for a project
        elif path == "/tasks" and method == "GET":
            project = params.get("project")
            if not project:
                return create_response(400, {"error": "Missing 'project' parameter"})

            response = table.query(
                KeyConditionExpression=Key("PK").eq(f"PROJECT#{project}")
                & Key("SK").begins_with("TASK#")
            )
            tasks = response.get("Items", [])
            return create_response(200, {"project": project, "tasks": tasks})

        # POST /tasks -> Create a task
        elif path == "/tasks" and method == "POST":
            body = parse_body(event)
            project = body.get("project")
            title = (body.get("title") or "").strip()
            assignee = (body.get("assignee") or "").strip()
            status = body.get("status") or "TODO"
            priority = body.get("priority") or "MEDIUM"
            blocker = (body.get("blocker") or "").strip()

            if not project or not title:
                return create_response(400, {"error": "Missing 'project' or 'title'"})

            task_id = body.get("id") or str(uuid.uuid4())[:8]
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
                "updated_at": datetime.datetime.utcnow().isoformat(),
            }
            table.put_item(Item=item)
            return create_response(201, {"message": "Task created successfully", "task": item})

        # PUT /tasks -> Update task status, assignee, title, or blocker
        elif path == "/tasks" and method == "PUT":
            body = parse_body(event)
            project = body.get("project")
            task_id = body.get("id")

            if not project or not task_id:
                return create_response(400, {"error": "Missing 'project' or 'id'"})

            update_parts = ["updated_at = :up"]
            expr_names = {}
            expr_values = {":up": datetime.datetime.utcnow().isoformat()}

            if "status" in body:
                update_parts.append("#st = :st")
                expr_names["#st"] = "status"
                expr_values[":st"] = body["status"]

            if "assignee" in body:
                update_parts.append("assignee = :asgn")
                expr_values[":asgn"] = body["assignee"]

            if "title" in body:
                update_parts.append("title = :ttl")
                expr_values[":ttl"] = body["title"]

            if "priority" in body:
                update_parts.append("priority = :prio")
                expr_values[":prio"] = body["priority"]

            if "blocker" in body:
                update_parts.append("blocker = :blk")
                expr_values[":blk"] = body["blocker"]

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
            body = parse_body(event) if event.get("body") else {}
            project = params.get("project") or body.get("project")
            task_id = params.get("id") or body.get("id")

            if not project or not task_id:
                return create_response(400, {"error": "Missing 'project' or 'id'"})

            table.delete_item(
                Key={"PK": f"PROJECT#{project}", "SK": f"TASK#{task_id}"}
            )
            return create_response(200, {"message": "Task deleted successfully"})

        return create_response(404, {"error": f"Path '{path}' with method '{method}' not found"})

    except ClientError as err:
        return create_response(500, {"error": err.response["Error"]["Message"]})
    except Exception as err:
        return create_response(500, {"error": str(err)})
