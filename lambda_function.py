import json
import os
import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "DailyScrum")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}


def handler(event, context):
    http_context = event.get("requestContext", {}).get("http", {})
    method = http_context.get("method", "GET")

    if method == "OPTIONS":
        return {"statusCode": 204, "headers": CORS_HEADERS}

    try:
        if method == "POST":
            raw_body = event.get("body", "{}")
            if event.get("isBase64Encoded", False):
                import base64

                raw_body = base64.b64decode(raw_body).decode("utf-8")

            body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body

            project = body.get("project")
            week = body.get("week")
            day = body.get("day")
            member = body.get("member")
            answers = body.get("answers", [])

            if not all([project, week, day, member]):
                return {
                    "statusCode": 400,
                    "headers": CORS_HEADERS,
                    "body": json.dumps(
                        {"error": "Missing fields: project, week, day, member"}
                    ),
                }

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

            return {
                "statusCode": 201,
                "headers": CORS_HEADERS,
                "body": json.dumps(
                    {
                        "message": f"Daily Scrum recorded for {member} ({week} - {day})",
                        "data": {
                            "project": project,
                            "week": week,
                            "day": day,
                            "member": member,
                            "answers": answers,
                        },
                    }
                ),
            }

        elif method == "GET":
            params = event.get("queryStringParameters") or {}
            project = params.get("project")
            week = params.get("week")
            day = params.get("day")
            member = params.get("member")

            if not all([project, week, day, member]):
                return {
                    "statusCode": 400,
                    "headers": CORS_HEADERS,
                    "body": json.dumps(
                        {"error": "Missing params: project, week, day, member"}
                    ),
                }

            response = table.get_item(
                Key={
                    "PK": f"PROJECT#{project}",
                    "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
                }
            )
            item = response.get("Item")

            if not item:
                return {
                    "statusCode": 404,
                    "headers": CORS_HEADERS,
                    "body": json.dumps({"error": "Daily Scrum not found"}),
                }

            return {
                "statusCode": 200,
                "headers": CORS_HEADERS,
                "body": json.dumps(
                    {
                        "message": f"Daily Scrum loaded for {member} ({week} - {day})",
                        "answers": item.get("answers", []),
                    }
                ),
            }

        return {
            "statusCode": 405,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": f"Method {method} not allowed"}),
        }

    except ClientError as err:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": err.response["Error"]["Message"]}),
        }
    except Exception as err:
        return {
            "statusCode": 500,
            "headers": CORS_HEADERS,
            "body": json.dumps({"error": str(err)}),
        }
