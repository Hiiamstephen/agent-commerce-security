# Data-model contract — Step 1

This document defines the intended schema and constraints. It is **not yet an applied database migration**. Implementation and database tests belong to later milestones.

All money is stored as integer minor units (`amount_minor`, US cents here). Every tenant-owned record carries `tenant_id`; every request checks it against server-verified context.

| Planned table | Important fields | Required invariant |
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
| `purchases` | `purchase_id`, `tenant_id`, `user_id`, `quote_id`, `request_id`, `request_fingerprint`, `amount_minor`, `status` | Unique `(tenant_id, request_id)`; same retry returns original result, changed arguments are rejected. |
| `mock_ledger` | `entry_id`, `purchase_id`, `tenant_id`, `delta_minor`, `currency` | At most one charge per purchase. No real funds move. |
| `audit_events` | `event_id`, `trace_id`, `span_id`, `parent_span_id`, `agent_id`, `action`, `resource_id`, `decision`, `reason_code`, `occurred_at` | Durable allow/deny evidence for handoffs and tool calls; no raw tokens or sensitive prompts. |
| `outbox` | `event_id`, `event_type`, `payload`, `created_at`, `delivered_at` | Accepted purchase event commits with purchase and ledger. Other security decisions also reach the outbox. |
| `security_events` | `event_id`, `event_type`, `trace_id`, `occurred_at`, `payload` | Unique `event_id` permits safe worker replay. |

## Transaction boundaries

- **Allowed purchase:** recheck authorization and quote; conditionally update remaining budget; insert purchase, one mock-ledger entry, and one outbox event in a single transaction.
- **Denied purchase or handoff:** make no mock charge. Persist the decision and reason as an audit event; route it to security telemetry. Sensitive actions fail closed if the required audit write is unavailable.
- **Worker delivery:** retry outbox rows until acknowledged; insert final security events by stable `event_id`. Delivery may happen more than once, but final event storage has one row per ID.

## Context packet contract

Protected metadata stays in the orchestrator: `run_id`, verified `tenant_id`, verified `user_id`, effective scopes, expiry, and parent span. Model-visible content contains only the objective, selected free facts, source IDs, trust labels, and a return schema. A model-written summary cannot overwrite protected metadata.

## Fixture mapping

`fixtures/seed.json` defines the fictional initial records, including a 50-cent Acme budget and one 50-cent paid report. It does **not** pre-create quotes, purchases, ledger entries, or audit events. Those are produced by the future application.
