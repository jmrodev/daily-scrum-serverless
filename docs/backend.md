# Backend Lambda Function Reference

This document explains the implementation details of the backend package [`lambda_app/`](../lambda_app/) (entry point [`lambda_function.py`](../lambda_function.py), a thin shim re-exporting `lambda_app.handler.handler`).

Module layout (all small, focused modules): `store.py` (AWS clients, responses, pagination), `tokens.py` (HMAC auth, gates, passwords), `mail.py` + `templates.py` (SMTP + HTML), `activity.py` (log + purge), `signup.py` / `confirm.py` / `login.py` / `otp.py` (auth endpoints), `email_config.py` / `admin_users.py` (admin), `projects.py` / `members.py`, `scrums.py` / `tasks.py`. Each domain module exposes `route(path, method, event, params, user_claims)` returning a response or `None`.

---

## 1. Runtime Environment & Dependencies

* **Runtime:** Python 3.11
* **Memory Allocation:** 128 MB (Lowest consumption footprint, ~10-40ms execution times).
* **Timeout:** 5 seconds (Ample headroom for DynamoDB single-digit millisecond latency).
* **Dependencies:**
  - `json` (Standard Library)
  - `os` (Standard Library)
  - `base64` (Standard Library)
  - `boto3` (AWS Lambda Built-In SDK)
  - `botocore.exceptions.ClientError` (AWS Lambda Built-In SDK)

---

## 2. Ingress & HTTP Event Handling

When invoked through a **Lambda Function URL**, the incoming payload follows the **AWS Lambda HTTP Payload Format v2.0**:

```python
http_context = event.get("requestContext", {}).get("http", {})
method = http_context.get("method", "GET")
```

### Preflight (CORS `OPTIONS`)
To support cross-origin requests from GitHub Pages (`https://jmrodev.github.io`), the function handles the preflight handshake:
```python
if method == "OPTIONS":
  return {"statusCode": 204, "headers": CORS_HEADERS}
```

### Base64 Payload Unpacking
Function URLs or proxies may encode JSON request bodies in base64. The handler safely handles both plain and base64 strings:
```python
raw_body = event.get("body", "{}")
if event.get("isBase64Encoded", False):
  raw_body = base64.b64decode(raw_body).decode("utf-8")
body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
```

---

## 3. Endpoints & Operations

### `POST` — Record Daily Scrum
1. Validates presence of mandatory fields: `project`, `week`, `day`, `member`.
2. Formulates `PK` and `SK`.
3. Calls `table.put_item(...)`.
4. Returns HTTP `201 Created` with confirmation metadata.

### `GET` — Retrieve Daily Scrum
1. Reads query string parameters from `event["queryStringParameters"]`.
2. Validates parameters.
3. Calls `table.get_item(...)`.
4. Returns HTTP `200 OK` with saved responses if found, or HTTP `404 Not Found` if nonexistent.

---

## 4. Error Handling Matrix

| Scenario | HTTP Status | Response Body |
| :--- | :--- | :--- |
| Missing mandatory fields / query params | `400 Bad Request` | `{"error": "Missing fields: ..."}` |
| Item not found in DynamoDB | `404 Not Found` | `{"error": "Daily Scrum not found"}` |
| Unsupported HTTP method (`PUT`, `DELETE`) | `405 Method Not Allowed` | `{"error": "Method PUT not allowed"}` |
| DynamoDB client error (throttling, permissions) | `500 Internal Server Error` | `{"error": "<AWS Error Message>"}` |
| Unexpected Python runtime exception | `500 Internal Server Error` | `{"error": "<Exception string>"}` |
