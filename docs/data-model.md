# DynamoDB Data Model & Access Patterns

This document describes the schema design, key strategy, and access patterns implemented in the `DailyScrum` DynamoDB table.

---

## 1. Table Schema Overview

The database leverages a **Single-Table Design** pattern using a compound primary key (`PK` and `SK`).

| Property | Value | Notes |
| :--- | :--- | :--- |
| **Table Name** | `DailyScrum` | Configurable via `TABLE_NAME` environment variable |
| **Partition Key (`PK`)** | `String` (`S`) | Groups items by project entity |
| **Sort Key (`SK`)** | `String` (`S`) | Hierarchical composite key for temporal and member scoping |
| **Billing Mode** | `PROVISIONED` | Enforces the permanent free tier |
| **Read Capacity Units** | `1` | Max 25 in Free Tier |
| **Write Capacity Units** | `1` | Max 25 in Free Tier |

---

## 2. Key Formatting Strategy

```
PK: PROJECT#{project_name}
SK: WEEK#{week_id}#DAY#{day_name}#MEMBER#{member_name}
```

### Example Item Record

```json
{
  "PK": "PROJECT#Sabato",
  "SK": "WEEK#WEEK 9#DAY#Lunes#MEMBER#Paz",
  "project": "Sabato",
  "week": "WEEK 9",
  "day": "Lunes",
  "member": "Paz",
  "answers": [
    "Implemented authentication logic",
    "Writing integration tests",
    "Awaiting API spec review"
  ],
  "updated_at": "2026-09-16T22:15:00Z"
}
```

---

## 3. Supported Access Patterns

### Pattern 1: Record or Update a Member's Daily Scrum
* **Operation:** `PutItem`
* **Complexity:** $O(1)$
* **Target:** Exact match on `PK` and `SK`.
* **Idempotency:** Re-submitting the form for the same project, week, day, and member seamlessly overwrites the previous entry, preventing duplicate rows.

### Pattern 2: Retrieve a Specific Member's Daily Update
* **Operation:** `GetItem`
* **Complexity:** $O(1)$
* **Parameters:**
  ```python
  Key = {
      "PK": f"PROJECT#{project}",
      "SK": f"WEEK#{week}#DAY#{day}#MEMBER#{member}",
  }
  ```
* **Read Cost:** Exactly 0.5 RCU (strongly consistent) or 0.25 RCU (eventually consistent).

### Pattern 3: Future Expansion — Query All Members for a Day or Week
Because the `SK` follows a hierarchical structure (`WEEK#...#DAY#...#MEMBER#...`), the application can easily query all daily scrums for an entire week or day without scanning the table:
* **Query Condition:**
  ```python
  KeyConditionExpression = Key('PK').eq('PROJECT#Sabato') & Key(
      'SK'
  ).begins_with('WEEK#WEEK 9#DAY#Lunes')
  ```
