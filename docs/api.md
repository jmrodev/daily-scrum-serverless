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
* **Request Body:**
  ```json
  { "name": "Mobile" }
  ```
* **Response `201 Created`:**
  ```json
  { "message": "Project 'Mobile' created" }
  ```

### `DELETE /projects/{name}`
Deletes a project record.
* **Response `200 OK`:**
  ```json
  { "message": "Project 'Mobile' deleted" }
  ```

---

## 2. Members Endpoints

### `GET /projects/{project}/members`
Lists all team members associated with a specific project.
* **Response `200 OK`:**
  ```json
  {
    "members": [
      { "name": "Paz", "project": "Sabato", "role": "Developer" },
      { "name": "Juan", "project": "Sabato", "role": "Developer" }
    ]
  }
  ```

### `POST /projects/{project}/members`
Adds a member to a project.
* **Request Body:**
  ```json
  { "project": "Sabato", "name": "Sofía", "role": "QA Engineer" }
  ```
* **Response `201 Created`:**
  ```json
  { "message": "Member 'Sofía' added to 'Sabato'" }
  ```

### `DELETE /projects/{project}/members/{name}`
Removes a member from a project.
* **Response `200 OK`:**
  ```json
  { "message": "Member 'Sofía' removed from 'Sabato'" }
  ```

---

## 3. Daily Scrum Endpoints

### `POST /scrums`
Records a member's daily scrum update.
* **Request Body:**
  ```json
  {
    "project": "Sabato",
    "week": "WEEK 9",
    "day": "Lunes",
    "member": "Paz",
    "answers": [
      "Completed database schema integration",
      "Building user management modal",
      "None"
    ]
  }
  ```
* **Response `201 Created`:**
  ```json
  {
    "message": "Daily Scrum recorded for Paz (WEEK 9 - Lunes)",
    "data": { ... }
  }
  ```

### `GET /scrums?project={project}&week={week}&day={day}&member={member}`
Fetches the daily scrum responses for a specific member and date.
* **Response `200 OK`:**
  ```json
  {
    "message": "Daily Scrum loaded for Paz (WEEK 9 - Lunes)",
    "answers": [
      "Completed database schema integration",
      "Building user management modal",
      "None"
    ]
  }
  ```
