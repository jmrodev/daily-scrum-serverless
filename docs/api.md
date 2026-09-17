# REST API Specification

This document details all endpoints exposed by the Lambda Function URL.

---

## Base Ingress
`https://<function-url-id>.lambda-url.<region>.on.aws/`

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

### `POST /projects`
Creates a new project.
* **Request Body:** `{ "name": "Mobile" }`
* **Response `201 Created`:** `{ "message": "Project 'Mobile' created" }`

### `PUT /projects/{name}`
Renames an existing project.
* **Request Body:** `{ "newName": "MobileApp" }`
* **Response `200 OK`:** `{ "message": "Project 'Mobile' renamed to 'MobileApp'" }`

### `DELETE /projects/{name}`
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
      { "name": "Paz", "project": "Sabato", "role": "Tech Lead" },
      { "name": "Juan", "project": "Sabato", "role": "Developer" }
    ]
  }
  ```

### `POST /projects/{project}/members`
Adds a member to a project.
* **Request Body:** `{ "project": "Sabato", "name": "Sofia", "role": "QA" }`
* **Response `201 Created`:** `{ "message": "Member 'Sofia' added to 'Sabato'" }`

### `PUT /projects/{project}/members/{name}`
Updates a member's name and/or role.
* **Request Body:** `{ "newName": "Sofia R.", "role": "QA Lead" }`
* **Response `200 OK`:** `{ "message": "Member 'Sofia' updated in 'Sabato'" }`

### `DELETE /projects/{project}/members/{name}`
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
        "answers": ["Sprint planning", "Architecture design", "None"]
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
    "member": "Paz",
    "answers": ["Completed schema", "Building matrix view", "None"]
  }
  ```
* **Response `200 OK` / `201 Created`:** `{ "message": "Daily Scrum recorded for Paz (WEEK 9 - Lunes)" }`

### `DELETE /scrums` (Delete Daily)
Deletes a single daily scrum record.
* **Request Body (or query params):**
  ```json
  {
    "project": "Sabato",
    "week": "WEEK 9",
    "day": "Lunes",
    "member": "Paz"
  }
  ```
* **Response `200 OK`:** `{ "message": "Daily Scrum deleted for Paz (WEEK 9 - Lunes)" }`
