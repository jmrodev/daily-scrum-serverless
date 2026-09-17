# REST API Specification

This document details all endpoints exposed by the Lambda Function URL.

---

## Base Ingress
`https://<function-url-id>.lambda-url.<region>.on.aws/`

---

## 0. Authentication Endpoints (Amazon Cognito)

Authentication is handled with Amazon Cognito User Pools (`50,000 MAUs Always Free`).
When authenticated, pass `Authorization: Bearer <idToken>` on all API calls.

### `POST /auth/signup`
Registers a new team member account.
* **Request Body:**
  ```json
  {
    "name": "Juan",
    "email": "juan@empresa.com",
    "password": "Password123"
  }
  ```
* **Response `201 Created`:**
  ```json
  {
    "message": "User registered successfully. Check your email for the confirmation code.",
    "email": "juan@empresa.com"
  }
  ```

### `POST /auth/confirm`
Confirms the user's email via the 6-digit confirmation code. Confirmed users are automatically assigned to the `Members` group.
* **Request Body:**
  ```json
  {
    "email": "juan@empresa.com",
    "code": "123456"
  }
  ```
* **Response `200 OK`:**
  ```json
  {
    "message": "Account verified! You can now log in."
  }
  ```

### `POST /auth/login`
Authenticates user with username/password and issues JWT tokens.
* **Request Body:**
  ```json
  {
    "email": "juan@empresa.com",
    "password": "Password123"
  }
  ```
* **Response `200 OK`:**
  ```json
  {
    "message": "Login successful",
    "idToken": "<JWT_ID_TOKEN>",
    "accessToken": "<JWT_ACCESS_TOKEN>",
    "refreshToken": "<REFRESH_TOKEN>",
    "user": {
      "email": "juan@empresa.com",
      "name": "Juan",
      "groups": ["Members"],
      "isAdmin": false
    }
  }
  ```

### `GET /auth/me`
Retrieves the active user session claims based on the Bearer token.
* **Headers:** `Authorization: Bearer <idToken>`
* **Response `200 OK`:**
  ```json
  {
    "user": {
      "email": "juan@empresa.com",
      "name": "Juan",
      "groups": ["Members"],
      "is_admin": false
    }
  }
  ```

---

## Role-Based Access Control (RBAC) Matrix

| Endpoint | Guest / Unauthenticated | Member (`Members` Group) | Admin (`Admins` Group) |
|---|---|---|---|
| `GET /projects` | Allowed (Read-only) | Allowed | Allowed |
| `POST /projects` | 403 Forbidden | 403 Forbidden | Allowed |
| `PUT /projects/{name}` | 403 Forbidden | 403 Forbidden | Allowed |
| `DELETE /projects/{name}` | 403 Forbidden | 403 Forbidden | Allowed |
| `GET /projects/{proj}/members` | Allowed (Read-only) | Allowed | Allowed |
| `POST /projects/{proj}/members` | 403 Forbidden | 403 Forbidden | Allowed |
| `PUT /projects/{proj}/members/{m}` | 403 Forbidden | 403 Forbidden | Allowed |
| `DELETE /projects/{proj}/members/{m}` | 403 Forbidden | 403 Forbidden | Allowed |
| `GET /scrums` | Allowed (Transparent board) | Allowed | Allowed |
| `POST, PUT, DELETE /scrums` | Open if no auth header; 403 if auth header is present | **Only own daily** (`member == user.name`) | Any member's daily |

---

## 1. Projects Endpoints

### `GET /projects`
Returns an array of all active projects.
* **Response `200 OK`:**
  ```json
  {
    "projects": [
      { "name": "Sabato", "created_at": "2026-09-16T22:30:00Z" },
      { "name": "Core", "created_at": "2026-09-16T22:30:00Z" }
    ]
  }
  ```

### `POST /projects` (Admin Only)
Creates a new project.
* **Request Body:** `{ "name": "Mobile" }`
* **Response `201 Created`:** `{ "message": "Project 'Mobile' created" }`

### `PUT /projects/{name}` (Admin Only)
Renames an existing project.
* **Request Body:** `{ "newName": "MobileApp" }`
* **Response `200 OK`:** `{ "message": "Project 'Mobile' renamed to 'MobileApp'" }`

### `DELETE /projects/{name}` (Admin Only)
Deletes a project record.
* **Response `200 OK`:** `{ "message": "Project 'Mobile' deleted" }`

---

## 2. Members Endpoints

### `GET /projects/{project}/members`
Lists all team members associated with a specific project.
* **Response `200 OK`:**
  ```json
  {
    "members": [
      { "name": "Paz", "project": "Sabato", "role": "Tech Lead", "email": "paz@empresa.com" },
      { "name": "Juan", "project": "Sabato", "role": "Developer", "email": "juan@empresa.com" }
    ]
  }
  ```

### `POST /projects/{project}/members` (Admin Only)
Assigns a member to a project.
* **Request Body:** `{ "project": "Sabato", "name": "Sofia", "role": "QA", "email": "sofia@empresa.com" }`
* **Response `201 Created`:** `{ "message": "Member 'Sofia' added to 'Sabato'" }`

### `PUT /projects/{project}/members/{name}` (Admin Only)
Updates a member's name, role, or email.
* **Request Body:** `{ "newName": "Sofia R.", "role": "QA Lead", "email": "sofia.r@empresa.com" }`
* **Response `200 OK`:** `{ "message": "Member 'Sofia' updated in 'Sabato'" }`

### `DELETE /projects/{project}/members/{name}` (Admin Only)
Removes a member from a project.
* **Response `200 OK`:** `{ "message": "Member 'Sofia' removed from 'Sabato'" }`

---

## 3. Daily Scrum Endpoints

### `GET /scrums?project={project}&week={week}` (Weekly Matrix)
Retrieves all daily scrums for a project across an entire week using a single DynamoDB query (`begins_with("WEEK#...")`).
* **Response `200 OK`:**
  ```json
  {
    "project": "Sabato",
    "week": "WEEK 9",
    "count": 4,
    "scrums": [
      {
        "project": "Sabato",
        "week": "WEEK 9",
        "day": "Lunes",
        "member": "Paz",
        "answers": ["Sprint planning", "Architecture design", "Ninguno"]
      }
    ]
  }
  ```

### `POST /scrums` or `PUT /scrums` (Save / Update Daily)
Records or updates a member's daily scrum.
* **Request Body:**
  ```json
  {
    "project": "Sabato",
    "week": "WEEK 9",
    "day": "Lunes",
    "member": "Juan",
    "answers": ["Maquetación completa", "Componentes de modales", "Ninguno"]
  }
  ```
* **Response `200 OK` / `201 Created`:** `{ "message": "Daily Scrum recorded for Juan (WEEK 9 - Lunes)" }`
* **Response `403 Forbidden`:** `{ "error": "Forbidden: You can only record or modify your own Daily Scrum (logged in as Juan)." }`

### `DELETE /scrums` (Delete Daily)
Deletes a single daily scrum record.
* **Request Body (or query params):**
  ```json
  {
    "project": "Sabato",
    "week": "WEEK 9",
    "day": "Lunes",
    "member": "Juan"
  }
  ```
* **Response `200 OK`:** `{ "message": "Daily Scrum deleted for Juan (WEEK 9 - Lunes)" }`
