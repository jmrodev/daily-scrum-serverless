"""AWS clients, table handle, response helpers, pagination."""
import base64
import json
import os
import boto3

TABLE_NAME = os.environ.get("TABLE_NAME", "DailyScrum")
USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
CLIENT_ID = os.environ.get("CLIENT_ID", "")

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME)
cognito_idp = boto3.client("cognito-idp")

RESPONSE_HEADERS = {
    "Content-Type": "application/json",
}


def create_response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": RESPONSE_HEADERS,
        "body": json.dumps(body),
    }


def parse_body(event):
    raw_body = event.get("body", "{}")
    if event.get("isBase64Encoded", False):
        raw_body = base64.b64decode(raw_body).decode("utf-8")
    return json.loads(raw_body) if isinstance(raw_body, str) else raw_body


def _b64url_encode(data):
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(segment):
    segment += "=" * ((4 - len(segment) % 4) % 4)
    return base64.urlsafe_b64decode(segment.encode("utf-8"))


def _query_all(**kwargs):
    """Query con paginación completa (1 RCU/WCU safe)."""
    items = []
    last = None
    while True:
        if last:
            kwargs["ExclusiveStartKey"] = last
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
    return items


def _scan_all(**kwargs):
    """Scan con paginación completa."""
    items = []
    last = None
    while True:
        if last:
            kwargs["ExclusiveStartKey"] = last
        resp = table.scan(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
    return items
