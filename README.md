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

**Step 2 complete locally:** bounded buyer and read-only researcher roles, checked handoff and return, per-tool authorization, replay mode, a local Ollama adapter, and runtime traces. A Qwen3 1.7B live run completed the free-data task in five steps with a sourced comparison and no purchase. Its answer used the runtime's labeled factual fallback because the small model did not produce a useful final comparison. The API, persistent audit log, database migrations, real quotes, purchase flow, and evaluation harness are **not implemented yet**.

Read the project-local [architecture](docs/architecture.md), [data model](docs/data-model.md), and [threat model](docs/threat-model.md) for the design. The separate learning blueprint lives outside this repository; these files are the public-safe project source of truth.

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

The runtime keeps user, tenant, scopes, and expiry outside model-visible context. It validates both handoff directions, rechecks each tool request, limits model steps and handoff hops, caps context size and elapsed time, and emits in-memory trace events. These checks use fixture users and scopes. Signed identity and durable audit storage belong to later milestones.

## Decisions already made

- Exactly two bounded roles: `buyer` and `researcher`. The researcher is read-only.
- Three agent-facing tools: `list_services`, `get_quote`, and `purchase_service`.
- The runtime supplies a stable purchase request ID; the model does not choose an amount, tenant, or scope.
- Authorization is checked at every handoff and tool action. A handoff never transfers purchase authority.
- Seller descriptions and agent summaries are untrusted data.
- Money is represented in integer cents. The charge and budget are simulated.
- The first working path is local and low-cost. A real tool-calling model is required for the final demo; deterministic fixture replay is the fallback.

## Next milestone

Implement signed identity, canonical quotes, purchase policy, and the atomic mock transaction. Then persist audit decisions and outbox events. Exercise a real model once a local Ollama model is available.

## Publication boundary

This folder is intended for a public GitHub repository **after review**. Before publishing, check for credentials, local databases, logs, private data, and unsupported claims. Do not claim production-scale security or real payment settlement from this demo.
