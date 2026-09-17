# Frontend Reference (`index.html`)

This document details the client-side architecture and integration patterns implemented in [`index.html`](../index.html).

---

## 1. Design Overview

* **Format:** Single-File Static Web Application (Vanilla HTML5, CSS3, and modern ES6+ JavaScript).
* **Bundle Size:** ~4 KB (zero NPM dependencies, zero build steps, instant load time).
* **Hosting:** Static CDN delivery via **GitHub Pages**.

---

## 2. Component Architecture

The interface is structured into three clear logical sections:

```
┌─────────────────────────────────────────────────────────┐
│ 1. Configuration Card                                   │
│    [Input: Lambda Function URL]                         │
├─────────────────────────────────────────────────────────┤
│ 2. Register Daily Card (POST)                           │
│    - Project, Week, Day, Member fields                  │
│    - 3 Daily Scrum questions (textareas)                │
│    - Submit button & asynchronous status banner         │
├─────────────────────────────────────────────────────────┤
│ 3. Query & Render Card (GET)                            │
│    - Lookup criteria inputs                             │
│    - Load button                                        │
│    - Asynchronous results container (Dynamic DOM)       │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Asynchronous Data Handling & CORS

### Submitting Data (`POST`)
```javascript
const res = await fetch(url, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload),
});
```
* Collects form inputs.
* Transmits as JSON payload.
* Displays success alert upon receiving HTTP `201`.

### Fetching & Rendering Data (`GET`)
```javascript
const queryUrl = `${url}?project=${project}&week=${week}&day=${day}&member=${member}`;
const res = await fetch(queryUrl, { method: "GET" });
const data = await res.json();

// Dynamic DOM rendering
const listHtml = data.answers
  .map((ans, idx) => `<li><strong>Pregunta ${idx + 1}:</strong> ${ans}</li>`)
  .join("");
resultsDiv.innerHTML = `<ul>${listHtml}</ul>`;
```
* Constructs query string parameters.
* Receives DynamoDB item attributes in JSON format.
* Dynamically generates and mounts HTML list elements into `#results`.
