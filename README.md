# Agent Commerce Security Demo

A **personal, synthetic** project for practicing secure AI-agent handoffs, tool authorization, a simulated purchase, and evaluation. It is inspired by general experience with rating services and rule engines. It does not use Circle code, customer data, internal rules, or production architecture.

## What a client does

A human user at a fictional company asks a buyer agent to compare three fictional API suppliers. The user allows up to **$0.50 of simulated spending** for one specifications and reliability report. The buyer can ask a read-only research agent for free facts, then decide whether the report is needed. Agents are software clients acting within the human user's authority; they are not allowed to grant themselves access.

## What this system will do

1. Verify the human caller and bind the run to a tenant, user, and approved budget.
2. Authorize a narrow buyer-to-researcher handoff and each agent tool call.
3. Give the researcher only catalog-read tools and a compact, sourced task context.
4. Let the buyer request a server-stored quote and propose a purchase.
5. Check current authorization, quote, seller, risk rules, and budget in trusted code.
6. Record one mock charge, purchase, and outbox event in one transaction; return a receipt and synthetic report.
7. Deliver security events with retry and deduplication, then evaluate normal and adversarial cases.

No live payment processor or real customer information is involved.

## Status

**Steps 3 and 4 implemented locally:** signed demo tokens, current user and scope checks, stored quotes, seller and spending rules, and atomic simulated purchases are connected to the two-agent runtime and a loopback API. PostgreSQL is the default; SQLite remains a zero-dependency fallback. Security decisions have durable trace and span IDs. Researcher events link to the buyer handoff, and the resumed buyer links to the researcher return. The purchase, budget update, mock ledger entry, audit decision, and outbox event commit together. A retrying local worker deduplicates final security events. PostgreSQL checks include a worker process crash before commit and a deliberate replay after delivery. The evaluation harness is a later milestone. A Step 2 Qwen3 1.7B run completed the free-data task using the runtime's labeled factual fallback; the paid path has been exercised in replay mode.

Read the project-local [architecture](docs/architecture.md), [data model](docs/data-model.md), and [threat model](docs/threat-model.md) for the design. The separate learning blueprint lives outside this repository; these files are the public-safe project source of truth.

The [Step 4 verification record](docs/step4-verification.md) gives a live run ID, trace links, crash and replay checks, and the remaining practical limits.

## Repository map

| Path | Purpose |
| --- | --- |
| `fixtures/seed.json` | Fictional tenants, users, agent roles, suppliers, seller, budget, and paid report. |
| `fixtures/tasks.json` | Four starter scenarios with expected outcomes. |
| `docs/architecture.md` | Human-readable flow and trust boundaries. |
| `docs/data-model.md` | Planned tables, keys, and invariants. |
| `docs/threat-model.md` | Assets, attacker capabilities, controls, and limits. |
| `scripts/validate_fixtures.py` | Standard-library check that seed and tasks are internally consistent. |
| `src/agent_commerce_security/` | Application package for later milestones. |
| `scripts/run_step2.py` | Run the bounded runtime in replay or local Ollama mode. |
| `src/agent_commerce_security/commerce.py` | Signed local tokens, current authorization, quotes, risk checks, and mock purchase transaction. |
| `src/agent_commerce_security/api.py` | Loopback HTTP API for catalog, quotes, and purchases. |
| `migrations/001_sqlite.sql` | Local transactional schema with constraints and unique request IDs. |
| `migrations/001_postgres.sql` | PostgreSQL schema for the same purchase path. |
| `scripts/run_step3.py` | Run a signed, database-backed scenario. |
| `scripts/serve_step3.py` and `scripts/issue_demo_token.py` | Serve the local API and issue a short-lived local test token. |
| `src/agent_commerce_security/audit.py` and `scripts/deliver_outbox.py` | Persist audit decisions and deliver queued events with replay protection. |
| `scripts/show_step4_evidence.py` | Inspect a run's trace links and final event delivery state. |
| `scripts/run_step4_denied.py` | Generate a reviewable denied handoff with no mock charge. |
| `scripts/reset_demo.py` | Restore only the dedicated PostgreSQL demo database to fictional seed state. |
| `tests/` | Security and evaluation tests for later milestones. |

## Check the Step 1 fixtures

Requires Python 3.13 or newer; no packages or services are needed for this check.

```sh
python3 scripts/validate_fixtures.py
```

The check validates references, uniqueness, integer money values, role/tool limits, and the two core task expectations. It does **not** run an LLM or prove security behavior.

## Run the Step 2 runtime

```sh
python3 scripts/run_step2.py task_free_sufficient
python3 scripts/run_step2.py task_paid_needed
python3 -m unittest discover -s tests -v
```

Replay mode is deterministic. The free task returns a sourced research packet and an answer without a purchase. The paid task reaches the buyer's quote preview, then stops at `PURCHASE_NOT_IMPLEMENTED`; it cannot charge a budget. To try a local model, start an Ollama server with a model installed and run `python3 scripts/run_step2.py task_free_sufficient --ollama-model MODEL_NAME --compact`. The adapter uses a state-specific JSON schema. If the buyer returns an incomplete answer, the runtime requests repair and may return a clearly labeled summary built from validated free facts. The observed Qwen3 1.7B run used that fallback; its successful completion does not establish consistent model answer quality.

The runtime keeps user, tenant, scopes, and expiry outside model-visible context. It validates both handoff directions, rechecks each tool request, limits model steps and handoff hops, and caps context size and elapsed time. The Step 3 path binds these checks to a signed token and current database permissions and persists minimal decision records.

## Run the Step 3 purchase path

PostgreSQL 16 and Psycopg 3 are required for the default Step 3 commands; setup is below. The signing key is created under ignored `local-data/` and readable only by the local user. The purchase, budget, and ledger are simulated; no real funds move.

```sh
.venv/bin/python scripts/run_step3.py task_paid_needed
.venv/bin/python scripts/run_step3.py task_free_sufficient
ACS_TEST_POSTGRES_DSN='dbname=agent_commerce_security_test' .venv/bin/python -m unittest discover -s tests -v
```

The first paid run on a fresh demo database buys the 50-cent report and leaves Alice's budget at zero. The second run denies a new purchase with `BUDGET_EXCEEDED`. The free task uses catalog facts and spends nothing. Add `--trace` to print decision events or `--ollama-model qwen3:1.7b` to let the local model propose actions. For the SQLite fallback, prefix a command with `ACS_STORE=sqlite`; `--reset` then deletes only the ignored local SQLite database and preserves the signing key.

To make a fresh PostgreSQL demo, run `.venv/bin/python scripts/reset_demo.py`. The command checks that it is connected to `agent_commerce_security_demo` before clearing only its fictional demo tables; it preserves the signing key. It deletes prior demo purchases and audit records in that dedicated database.

For direct HTTP calls, run `.venv/bin/python scripts/serve_step3.py` in one terminal. In another, use `.venv/bin/python scripts/issue_demo_token.py user_alice` to obtain a 15-minute token. Send it as `Authorization: Bearer <token>` to `GET /v1/catalog`, `POST /v1/quotes` with `{"service_id":"service_reliability_report"}`, or `POST /v1/purchases` with `{"quote_id":"...","request_id":"stable-client-request-id"}`. The API accepts no client price or tenant field. Treat the printed token as a local credential and do not commit it.

The local API handler and transaction have automated checks. The live API was checked on loopback with a healthy response, an unauthenticated 401, and an authenticated catalog 200.

### Deliver security events

Audit decisions are written to `audit_events` and queued in `outbox`. Allowed quotes and purchases write their audit row in the same transaction as the business change. Run `.venv/bin/python scripts/deliver_outbox.py --watch` in another terminal to deliver continuously, or omit `--watch` to process one batch. The worker retries failures and uses unique event IDs in `security_events`; replaying a previously delivered row does not create a duplicate. A duplicate ID with different content stops delivery for inspection. This is a local database sink, not an external security platform.

Inspect the existing runs using the IDs in [Step 4 verification](docs/step4-verification.md) before resetting the database. To generate fresh Step 4 evidence, run:

```sh
.venv/bin/python scripts/reset_demo.py
.venv/bin/python scripts/run_step3.py task_paid_needed --trace
.venv/bin/python scripts/run_step4_denied.py
.venv/bin/python scripts/deliver_outbox.py
.venv/bin/python scripts/show_step4_evidence.py
ACS_TEST_POSTGRES_DSN='dbname=agent_commerce_security_test' .venv/bin/python -m unittest discover -s tests -p 'test_step3_postgres.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_step4.py' -v
```

The Step 4 checks verify linked buyer and researcher spans, a durable denied handoff, purchase and audit rollback together, a worker process crash before commit, and one final event per ID after replay. `reset_demo.py` deletes earlier fictional demo events in that dedicated database.

### Use PostgreSQL on your Mac

The PostgreSQL default requires a local PostgreSQL server and Psycopg 3. Use a dedicated demo database. The demo's startup creates its tables and inserts fictional seed data if absent; it does not clear purchases or restore budgets. The test command below uses a separate database named exactly `agent_commerce_security_test` and clears its demo tables before every test. Do not point it at a database containing other data.

```sh
brew services start postgresql@16
pg_isready
python3 -m venv .venv
.venv/bin/python -m pip install 'psycopg[binary]'
createdb agent_commerce_security_demo
createdb agent_commerce_security_test
.venv/bin/python scripts/run_step3.py task_paid_needed
ACS_TEST_POSTGRES_DSN='dbname=agent_commerce_security_test' .venv/bin/python -m unittest discover -s tests -p 'test_step3_postgres.py' -v
```

Set `ACS_POSTGRES_DSN` to override the default `dbname=agent_commerce_security_demo` connection string. `scripts/reset_demo.py` refuses to clear any database with another name.

## Decisions already made

- Exactly two bounded roles: `buyer` and `researcher`. The researcher is read-only.
- Three agent-facing tools: `list_services`, `get_quote`, and `purchase_service`.
- The runtime supplies a stable purchase request ID; the model does not choose an amount, tenant, or scope. Direct API clients supply a request ID for retry safety.
- Authorization is checked at every handoff and tool action. A handoff never transfers purchase authority.
- Seller descriptions and agent summaries are untrusted data.
- Money is represented in integer cents. The charge and budget are simulated.
- The first working path is local and low-cost. A real tool-calling model is required for the final demo; deterministic fixture replay is the fallback.

## Next milestone

Build the broader evaluation harness and exercise a live model on normal and adversarial scenarios. Production payments, identity providers, and external telemetry remain outside this local simulated project.

## Publication boundary

This folder is in a public GitHub repository. Before pushing a change, check for credentials, local databases, logs, private data, and unsupported claims. Do not claim production-scale security or real payment settlement from this demo.
