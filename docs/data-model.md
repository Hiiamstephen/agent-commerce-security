# Data-model contract

The local demo applies `migrations/001_postgres.sql` by default or `migrations/001_sqlite.sql` with `ACS_STORE=sqlite`. Both schemas cover tenants, users, sellers, services, paid reports, budgets, quotes, purchases, the mock ledger, audit decisions, outbox, and final security events. The remaining tables below are planned for later milestones. PostgreSQL migration and transaction behavior were checked on the local PostgreSQL 16 server.

All money is stored as integer minor units (`amount_minor`, US cents here). Every tenant-owned record carries `tenant_id`; every request checks it against server-verified context.

| Table | Important fields | Required invariant |
| --- | --- | --- |
| `tenants` | `tenant_id`, `display_name` | Stable unique tenant ID. |
| `demo_users` | `user_id`, `tenant_id`, `active` | User belongs to exactly one demo tenant. |
| `agent_roles` and `agent_tool_grants` | `agent_id`, `tool_name`, `allowed` | Researcher has `list_services` only. Tool grants are server-owned. |
| `budgets` | `budget_id`, `tenant_id`, `user_id`, `currency`, `limit_minor`, `remaining_minor`, `version` | Nonnegative amount; one active budget per user and currency for the demo; update atomically. |
| `catalog_items` | `item_id`, `supplier_name`, `free_fields`, `source_id` | All displayed suppliers and free facts are synthetic. |
| `services` | `service_id`, `seller_id`, `price_minor`, `currency`, `active`, `description` | Seller description is untrusted; price and seller ID are authoritative server data. |
| `quotes` | `quote_id`, `tenant_id`, `user_id`, `service_id`, `amount_minor`, `currency`, `expires_at`, `version` | Quote is bound to caller, service, price, currency, and expiry. Purchase re-reads it. |
| `runs` | `run_id`, `trace_id`, `tenant_id`, `user_id`, `status`, `started_at` | One verified caller context per run. |
| `handoffs` | `handoff_id`, `run_id`, `sender_agent_id`, `recipient_agent_id`, `scope`, `expires_at`, `decision`, `reason_code` | One-hop read-only buyer → researcher handoff; each direction is checked and traced. |
| `purchases` | `purchase_id`, `tenant_id`, `user_id`, `quote_id`, `request_id`, `request_fingerprint`, `amount_minor`, `receipt_json` | Unique `(tenant_id, request_id)` and `quote_id`; same retry returns original result, changed arguments are rejected. |
| `mock_ledger` | `entry_id`, `purchase_id`, `tenant_id`, `delta_minor`, `currency` | At most one charge per purchase. No real funds move. |
| `audit_events` | `event_id`, `run_id`, `trace_id`, `span_id`, `parent_span_id`, `tenant_id`, `user_id`, `role`, `action`, `decision`, `reason_code`, `occurred_at` | Durable allow/deny evidence for handoffs and tool calls; no raw tokens or prompts. |
| `outbox` | `event_id`, `event_type`, `payload_json`, `created_at`, `delivered_at` | Accepted purchase event commits with purchase and ledger. Other security decisions also reach the outbox. |
| `security_events` | `event_id`, `event_type`, `trace_id`, `occurred_at`, `payload_json` | Unique `event_id` permits safe worker replay in the local sink. |

## Transaction boundaries

- **Allowed purchase:** recheck authorization and quote; conditionally update remaining budget; insert purchase, one mock-ledger entry, audit event, and outbox row in one transaction. SQLite uses `BEGIN IMMEDIATE`; PostgreSQL uses a transaction, a request-key advisory lock, quote row lock, and conditional budget update. One quote can be purchased once. Failure to write the audit row rolls the purchase back.
- **Denied purchase or handoff:** make no mock charge. Return a reason code and persist a minimal audit decision and outbox row in a separate transaction. If that write is unavailable, the operation fails closed.
- **Worker delivery:** retry pending outbox rows; insert final security events by stable `event_id` in the same local database. Delivery may be retried, but final event storage has one row per ID. This does not represent external telemetry delivery.

## Context packet contract

Protected metadata stays in the orchestrator: `run_id`, verified `tenant_id`, verified `user_id`, effective scopes, expiry, and parent span. Model-visible content contains only the objective, selected free facts, source IDs, trust labels, and a return schema. A model-written summary cannot overwrite protected metadata.

## Fixture mapping

`fixtures/seed.json` defines the fictional initial records, including a 50-cent Acme budget and one 50-cent paid report. It does **not** pre-create quotes, purchases, ledger entries, or audit events. Local runs create these as actions occur.

The seed also holds trusted `task_requirements`. The paid error-rate task names the report service needed to answer it and grants that one service for purchase; free tasks grant no service. These requirements are not taken from a model response. The runtime rejects a free-catalog-only finish for the paid task and denies purchase proposals without a task-issued quote and service grant. The purchase service still decides whether an otherwise valid proposal may spend. A direct API caller currently has no signed task grant, which is a deployment boundary documented in the security benchmark contract.
