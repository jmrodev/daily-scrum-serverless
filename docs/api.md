# REST API Specification

This document details all endpoints exposed by the Lambda Function URL.

---

## Base Ingress
`https://<function-url-id>.lambda-url.<region>.on.aws/`

---

## 0. Authentication (HMAC server tokens — canónico)

Auth canónica: tokens HMAC-SHA256 propios (`mint_token`/`verify_token` con `TOKEN_SECRET`, TTL 7 días) sobre usuarios en DynamoDB (`USER#{email}` con PBKDF2). Cognito User Pool + App Client se siguen provisionando en `deploy.sh` solo como fallback/legado: `extract_user_claims` acepta un Id token Cognito cuando `CLIENT_ID` está configurado, y el borrado de cuenta también purga Cognito. Todo el flujo signup/confirm/login/OTP es custom, no Cognito.
Cuando estés autenticado, pasá `Authorization: Bearer <token>` en todas las llamadas.

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
* **Headers:** `Authorization: Bearer <token>`
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

### `POST /auth/otp/request`
Passwordless OTP por email (Gmail SMTP).
* Throttle: 1 envío/minuto por email (`429`); bloqueo 5 min tras 5 fallos.
* **Response `200 OK`:** `{ "message": "Código enviado con éxito a ...", "sent": true }`

### `POST /auth/otp/verify`
Valida el código de 6 dígitos (10 min) y emite sesión HMAC.
* Mensajes genéricos anti-enumeración: `Código inválido o expirado. Solicitá uno nuevo.` Al 5º fallo → `429`, se invalida el código.

---

## Role-Based Access Control (RBAC) Matrix

| Endpoint | Guest / Unauthenticated | Member (`Members` Group) | Admin (`Admins` Group) |
|---|---|---|---|
| `GET /projects` | 401 Unauthorized | Allowed | Allowed |
| `POST /projects` | 403 Forbidden | 403 Forbidden | Allowed |
| `PUT /projects/{name}` | 403 Forbidden | 403 Forbidden | Allowed |
| `DELETE /projects/{name}` | 403 Forbidden | 403 Forbidden | Allowed |
| `GET /projects/{proj}/members` | 401 Unauthorized | Allowed | Allowed |
| `POST /projects/{proj}/members` | 403 Forbidden | **Self-assignment only** if `allow_self_assignment: true`; otherwise 403 | Any member |
| `PUT /projects/{proj}/members/{m}` | 403 Forbidden | 403 Forbidden | Allowed |
| `DELETE /projects/{proj}/members/{m}` | 403 Forbidden | **Self un-assignment only** if `allow_self_assignment: true`; otherwise 403 | Any member |
| `GET /scrums` | 401 Unauthorized | Allowed | Allowed |
| `POST, PUT, DELETE /scrums` | 401 Unauthorized | **Only own daily** (`member == user.name`) | Any member's daily |
| `GET /tasks` | 401 Unauthorized | Allowed | Allowed |
| `POST, PUT, DELETE /tasks` | 401 Unauthorized | Allowed | Allowed |

---

## 1. Projects Endpoints

### `GET /projects`
Returns an array of all active projects with their self-assignment configuration.
* **Response `200 OK`:**
  ```json
  {
    "projects": [
      { "name": "Sabato", "allow_self_assignment": false, "created_at": "2026-09-16T22:30:00Z" },
      { "name": "Mobile", "allow_self_assignment": true, "created_at": "2026-09-16T22:30:00Z" }
    ]
  }
  ```

### `POST /projects` (Admin Only)
Creates a new project with optional self-assignment toggle.
* **Request Body:** `{ "name": "Mobile", "allow_self_assignment": true }`
* **Response `201 Created`:** `{ "message": "Project 'Mobile' created" }`

### `PUT /projects/{name}` (Admin Only)
Renames an existing project or toggles `allow_self_assignment`.
* **Request Body:** `{ "newName": "MobileApp", "allow_self_assignment": false }`
* Rename migra members + scrums + tasks de `PROJECT#{old}` a `PROJECT#{new}`. Si el destino ya existe → `400`.
* **Response `200 OK`:** `{ "message": "Project 'MobileApp' updated" }`

### `DELETE /projects/{name}` (Admin Only)
Moves the project + all its items to trash (soft cascade, restorable 30 días, TTL gratis). Re-crear el proyecto lo restaura con todo su contenido.
* **Response `200 OK`:** `{ "message": "Project 'Mobile' moved to trash", "trashed_items": 12 }`

### `GET /admin/trash?project={name}` (Admin Only)
Lists trashed items of a project (members, tasks, scrums) with restore keys.
* **Response `200 OK`:** `{ "project": "Sabato", "count": 3, "trash": [{ "pk": "...", "sk": "...", "kind": "task", "title": "...", "deleted_at": "..." }] }`

### `POST /admin/trash/restore` (Admin Only)
Restores one trashed item.
* **Request Body:** `{ "project": "Sabato", "pk": "PROJECT#Sabato", "sk": "TASK#abc123" }`
* **Response `200 OK`:** `{ "message": "Item restored from trash" }`

### `DELETE /admin/trash` (Admin Only)
Purges one trashed item forever (no hay deshacer).
* **Request Body:** `{ "project": "Sabato", "pk": "PROJECT#Sabato", "sk": "TASK#abc123" }`
* **Response `200 OK`:** `{ "message": "Item purged forever" }`

### `POST /tasks/restore` / `POST /scrums/restore`
Restore one trashed task / daily (los usa el botón Deshacer).
* **Response `200 OK`:** `{ "message": "Task restored from trash" }`

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

### `DELETE /projects/{project}/members/{name}` (Admin or self un-assignment)
Removes the membership from THIS project only — the user account is always preserved. Full account purge lives only in `DELETE /admin/users/{email}`.
* **Response `200 OK`:** `{ "message": "Member 'Sofia' removed from 'Sabato' (account preserved)" }`

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

### `DELETE /scrums` (Move Daily to Trash)
Moves a single daily scrum record to trash (restorable 30 días).
* **Request Body (or query params):**
  ```json
  {
    "project": "Sabato",
    "week": "WEEK 9",
    "day": "Lunes",
    "member": "Juan"
  }
  ```
* **Response `200 OK`:** `{ "message": "Daily Scrum moved to trash for Juan (WEEK 9 - Lunes)" }`
