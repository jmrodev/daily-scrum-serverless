# DynamoDB Data Model & Access Patterns

This document describes the schema design, key strategy, and access patterns implemented in the `DailyScrum` DynamoDB table.

---

## 1. Table Schema Overview

The database leverages a **Single-Table Design** pattern using a compound primary key (`PK` and `SK`), accommodating three distinct entity types in one table:

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Table Name** | `DailyScrum` | Configurable via `TABLE_NAME` environment variable |
| **Partition Key (`PK`)** | `String` (`S`) | Entity partition boundary |
| **Sort Key (`SK`)** | `String` (`S`) | Entity type and hierarchical identifier |
| **Billing Mode** | `PROVISIONED` | Enforces the permanent free tier |
| **Read Capacity Units** | `1` | Max 25 in Free Tier |
| **Write Capacity Units** | `1` | Max 25 in Free Tier |

---

## 2. Entity Mapping & Key Strategy

| Entity | `PK` | `SK` | Attributes |
| :--- | :--- | :--- | :--- |
| **Project** | `META#PROJECTS` | `PROJECT#{name}` | `name`, `created_at` |
| **Member** | `PROJECT#{project}` | `MEMBER#{name}` | `name`, `project`, `role`, `created_at` |
| **Daily Scrum** | `PROJECT#{project}` | `WEEK#{week}#DAY#{day}#MEMBER#{name}` | `project`, `week`, `day`, `member`, `answers`, `updated_at` |

---

## 3. Supported Access Patterns

### Pattern 1: Projects CRUD
* **List all projects:** `Query(PK == "META#PROJECTS")`
* **Create project:** `PutItem(PK = "META#PROJECTS", SK = "PROJECT#{name}")`
* **Delete project:** `DeleteItem(PK = "META#PROJECTS", SK = "PROJECT#{name}")`

### Pattern 2: Members CRUD (Scoped to Project)
* **List members of a project:** `Query(PK == "PROJECT#{project}" AND SK begins_with "MEMBER#")`
* **Add member to project:** `PutItem(PK = "PROJECT#{project}", SK = "MEMBER#{name}")`
* **Remove member:** `DeleteItem(PK = "PROJECT#{project}", SK = "MEMBER#{name}")`

### Pattern 3: Daily Scrums
* **Record daily scrum:** `PutItem(PK = "PROJECT#{project}", SK = "WEEK#{week}#DAY#{day}#MEMBER#{name}")`
* **Retrieve daily scrum:** `GetItem(PK = "PROJECT#{project}", SK = "WEEK#{week}#DAY#{day}#MEMBER#{name}")`
* **Query all daily scrums for a day (Future):** `Query(PK == "PROJECT#{project}" AND SK begins_with "WEEK#{week}#DAY#{day}")`

---

## 4. Soft-Delete / Trash (100% Always Free)

Nothing is hard-deleted except explicit account purges (`DELETE /admin/users`) and trash purges (`DELETE /admin/trash`). Deletes set `deleted = true` + `deleted_at` + `ttl` (+30d, auto-purged free via DynamoDB TTL on `ttl`).

* All list queries filter `attribute_not_exists(#del)` (`#del` → `deleted`, aliased: reserved-word safe).
* Single-item reads treat flagged items as not found.
* Restore = `REMOVE deleted, deleted_at, ttl`. Re-adding a trashed member / re-creating a trashed project restores it with its content.
* Trash audit events live under `PK = AUDIT#PROJECT#{project}` (`TRASH` / `RESTORE` / `PURGE` actions, 90d TTL).
