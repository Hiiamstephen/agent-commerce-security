# Threat assumptions — local demo

This is a learning threat model for a **local, simulated** agent-commerce demo. It states what the implementation and tests defend. Passing the local checks does not establish production security.

## Assets to protect

- Alice's and Bob's tenant-scoped catalog access and report results.
- Each user's simulated budget and mock ledger.
- Authenticity of quotes, authorization decisions, handoff context, and audit evidence.
- The demo token signing key and any optional model API key.

## Trust boundaries

| Boundary | Untrusted or changeable input | Trusted decision point |
| --- | --- | --- |
| Human or client → API | Task text, token presented by caller | Token verification plus current user/tenant/scope lookup. |
| Buyer → researcher | Requested subtask and proposed context | Handoff gate checks user, tenant, recipient, allowed read scope, expiry, and hop count. |
| Researcher → buyer | Findings, summaries, and seller text | Return gate checks packet origin/schema and keeps protected metadata outside model output. |
| Agent → tool | Tool name and model-generated arguments | Tool gateway checks role allowlist, user authority, resource, and current policy on every call. |
| Buyer → purchase | Quote ID, service ID, request ID | Agent runtime checks a trusted task spend grant and its issued quote; purchase API re-reads canonical quote, checks risk and budget, and performs one atomic write. |
| Outbox → event store | Duplicate or delayed delivery | Stable event ID and unique final event record. |

## Attacker capabilities assumed for tests

An attacker can craft task or seller text, try to make a model call the wrong tool, propose a forged or over-scoped handoff packet, submit another tenant's IDs, reuse a request ID with changed arguments, race two purchase requests, and trigger a worker crash or timeout. We also test missing, expired, forged, and wrong-audience demo tokens.

The attacker cannot directly edit the database, alter the server's signing key, or control the trusted authorization code. Those require separate infrastructure and supply-chain testing outside this demo.

## Controls and local evidence

| Threat | Planned control | Test evidence to collect |
| --- | --- | --- |
| Seller prompt injection | Seller text remains untrusted; no authority comes from prompts. | Live corpus probes 12 payloads; a forced model spend on a free task is denied by the runtime grant. |
| Agent privilege escalation | Effective permission = current user authority ∩ task grant ∩ recipient tool allowlist ∩ resource policy. | Researcher cannot call `purchase_service`; forged handoff is denied and traced. |
| Cross-tenant read or purchase | Tenant derived from verified server context and checked at every boundary. | Alice cannot read or buy Beta's resource; zero charge. |
| Context leakage or corruption | Protected metadata outside prompts; minimal sourced packet; schema, size, expiry, and origin checks. | Reject wrong-tenant/stale packet; preserve source IDs and uncertainty. |
| Quote or price tampering | Server-stored quote is re-read at purchase; model price ignored. | Changed or expired quote yields denial and zero charge. |
| Double charge after retry | Tenant-scoped stable request ID, fingerprint, atomic budget/ledger write. | Same retry returns original result; changed arguments rejected. |
| Budget race | Conditional/locked update in one transaction. | Two simultaneous requests for last 50 cents produce at most one charge. |
| Lost or duplicate telemetry | Audit event + outbox; retrying worker; unique final event ID. | Crash/replay yields one final event per ID and a linked trace. |
| Runaway agent | Step, time, tool, and handoff limits in runtime harness. | Invalid tool call or loop stops without side effect. |

## Audit and privacy rules

Record run and trace IDs, parent/child span IDs, agent role, user and tenant references, action, resource ID, allow/deny, reason code, policy version, and timestamp. Do not store raw bearer tokens, signing keys, model API keys, or full sensitive prompts in events. The dataset uses invented names and numbers only.

## Explicit limits

This project does not use real payments, a production identity provider, a cloud deployment, or real customer records. The security event sink is a local database table, not an external monitoring platform. Passing local tests cannot establish universal prompt-injection resistance, legal compliance, or production-scale reliability. Only measured demo results are claimed.
