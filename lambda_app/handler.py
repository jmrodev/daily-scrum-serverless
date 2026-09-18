"""Thin router: parses the Function URL event and dispatches to domain modules."""
from botocore.exceptions import ClientError

from . import admin_users, confirm, email_config, login, members, otp, projects, scrums, signup, tasks, trash
from .store import RESPONSE_HEADERS, create_response
from .tokens import extract_user_claims


def handler(event, context):
    http_context = event.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET")
    raw_path = event.get("rawPath", "/")
    path = raw_path.rstrip("/")
    if not path:
        path = "/"

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": RESPONSE_HEADERS}

    params = event.get("queryStringParameters") or {}
    user_claims = extract_user_claims(event)

    try:
        for route in (
            signup.route,
            confirm.route,
            login.route,
            otp.route,
            email_config.route,
            admin_users.route,
            projects.route,
            members.route,
            scrums.route,
            tasks.route,
            trash.route,
        ):
            response = route(path, method, event, params, user_claims)
            if response is not None:
                return response

        return create_response(404, {"error": f"Path '{path}' with method '{method}' not found"})

    except ClientError as err:
        print(f"ClientError in handler [{method} {path}]: {err}")
        return create_response(500, {"error": err.response["Error"]["Message"]})
    except Exception as err:
        import traceback
        traceback.print_exc()
        print(f"Exception in handler [{method} {path}]: {err}")
        return create_response(500, {"error": str(err)})
