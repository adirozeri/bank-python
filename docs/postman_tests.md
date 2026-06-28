# Postman Collection — Test Reference

This document explains every request in `postman/bank-python.postman_collection.json` and
what its test script asserts. The collection is organised by the
[Practical Test Pyramid](https://martinfowler.com/articles/practical-test-pyramid.html);
each top-level folder maps to a test type that makes sense for a black-box HTTP client.

## Collection variables

| Variable | Purpose |
|----------|---------|
| `baseUrl` | API root, defaults to `http://localhost:8000`. |
| `integ_txn_id` | Transaction id created in the Integration folder, reused by later requests there. |
| `e2e_txn_id` | Transaction id created during the End-to-End journey. |
| `e2e_thread_id` | LLM conversation/thread id captured in the End-to-End journey for the follow-up. |

> **Tip:** Folders whose requests share variables are **order-dependent**. Run them
> top-to-bottom with the Postman Collection Runner.

---

## 1. Integration Tests

> Test the API's integration with its database: write data through the app, then read it
> back to prove the round-trip persists.

### Write: create a transaction
`POST /transactions` — creates a debit of `125.50` for `ACC-0001`.
Asserts:
- Response code is `200` or `201`.
- The DB assigned a non-empty string `id`.
- `amount` round-trips unchanged (`125.5`).
- The given `status` (`completed`) was persisted.
- Saves the new `id` into `integ_txn_id` for the next requests.

### Read back: fetch it by id
`GET /transactions/{{integ_txn_id}}` — reads the record just created.
Asserts:
- `200 OK`.
- The returned `id` equals `integ_txn_id` (same record came back out of the DB).
- `account_id` matches what was written (`ACC-0001`).

### Read: filter reaches the DB (WHERE account_id)
`GET /transactions?account_id=ACC-0001` — proves the filter is pushed to the query.
Asserts:
- `200 OK`.
- The response body is an array.
- Every row honours the filter (`account_id === 'ACC-0001'`).

---

## 2. Contract Tests (CDC)

> A lightweight stand-in for Consumer-Driven Contracts. Postman can't do a full Pact
> handshake, so each request asserts the response matches the JSON schema consumers rely on.
> Treat these as the documented response contract for the provider.

### Contract: /health
`GET /health`.
Asserts:
- Response matches schema `{ status: string }` (object, `status` required).
- `status` equals `"ok"`.

### Contract: transaction object (POST /transactions)
`POST /transactions` — creates a pending credit of `42.00`.
Asserts the response matches the transaction contract:
- Required fields: `id`, `account_id`, `amount`, `currency`, `type`, `status`.
- Typed optional/nullable fields: `counterparty`, `category`, `description` (`string` or `null`).

### Contract: transaction list (GET /transactions)
`GET /transactions`.
Asserts the response is an **array** of objects, each matching the transaction contract
(required: `id`, `account_id`, `amount`, `currency`, `type`, `status`).

### Contract: /ask response
`POST /ask` with a natural-language question.
Asserts the response matches the `/ask` contract:
- Required: `thread_id` (string), `answer` (string) — and nothing else.
- The reply never exposes `queries`, `sql`, or `rows` (SQL/rows stay internal).

---

## 3. End-to-End Tests

> One high-value user journey through the real API. Order-dependent — run top-to-bottom.

### Step 1: customer makes a transaction
`POST /transactions` — a `9.99` debit (coffee) on `ACC-0001`.
Asserts:
- Created (`200`/`201`).
- Saves the new `id` into `e2e_txn_id`.

### Step 2: it appears in the account's history
`GET /transactions?account_id=ACC-0001`.
Asserts:
- `200 OK`.
- The list of ids includes `e2e_txn_id` (the new transaction shows up).

### Step 3: analyst asks the assistant about the account
`POST /ask` — "show me the transactions for account ACC-0001".
Asserts:
- `200 OK`.
- A non-empty natural-language `answer` is returned.
- No SQL/rows are exposed to the caller (`queries` is `undefined`).
- Saves `thread_id` into `e2e_thread_id`.

### Step 4: follow-up in the same conversation
`POST /ask` — "what is its balance?" reusing `{{e2e_thread_id}}`.
Asserts:
- `200 OK`.
- The follow-up is answered with a non-empty `answer` (proves conversation memory).

---

## 4. Acceptance Tests

> Business rules in plain language (Given / When / Then), asserting observable behaviour
> rather than implementation.

### Scenario: a new transaction defaults currency to USD
`POST /transactions` — a credit with no `currency` supplied.
Asserts:
- It is stored with the `status` it was given (`completed`).
- `currency` defaults to `USD` when not supplied.

### Scenario: looking up an unknown transaction is rejected
`GET /transactions/does-not-exist`.
Asserts:
- The API responds `404`.
- The error `detail` is `"Transaction not found"`.

### Scenario: an analyst can ask a question in plain English
`POST /ask` — "how many transactions does ACC-0001 have?".
Asserts:
- A non-empty, human-readable `answer` is returned.

### Scenario: a money transfer must be confirmed before it happens
`POST /ask` — "I'm ACC-0001, transfer 100 USD to ACC-0002".
Asserts (the guardrail for money-moving actions):
- The assistant's `answer` asks to `confirm` before moving money.
- The reply exposes no SQL/rows (`queries` is `undefined`).

---

## 5. Examples (manual driving, no assertions)

The original hand-driving requests, kept for poking at endpoints by hand. **No test
scripts.**

| Request | Call |
|---------|------|
| Health | `GET /health` |
| Create Transaction | `POST /transactions` (debit, groceries) |
| List Transactions | `GET /transactions` |
| Get Transaction | `GET /transactions/PASTE_ID_HERE` |
| Ask (LLM) - new conversation | `POST /ask` (question only) |
| Ask (LLM) - follow-up (same thread) | `POST /ask` (question + `thread_id`) |
| Ask (LLM) - transfer Step 1: request | `POST /ask` (transfer request → awaits confirmation) |
| Ask (LLM) - transfer Step 2: confirm with 'yes' | `POST /ask` ("yes" + `thread_id`) |

---

## What is intentionally *not* in this collection

- **Unit tests** — run in-process against functions/classes with mocks; belong in pytest.
- **UI tests** — the API is headless/backend-only; nothing to drive over HTTP.
- **Exploratory tests** — manual and creative by definition; cannot be automated.
