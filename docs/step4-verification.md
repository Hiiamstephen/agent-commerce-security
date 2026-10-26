# Step 4 verification

The checks below ran against local PostgreSQL 16 on 2026-10-25. The fixtures and charge are synthetic.

## Reviewable run

- Run ID: `e2796c72c77c4b57876dfb4904bbcfc0`
- Trace ID: `64e27285024041328f4420e5795225f6`
- Result: one 50-cent mock purchase, one ledger entry, 11 audit rows, 11 outbox rows, and 11 final security events.
- The researcher model, catalog call, and return use the buyer handoff span `8a769861830f4b0794b662d4f3115509` as their parent. After the return span `001e3df4e4cc47ed8581d14fb3816423`, the buyer quote and purchase use that return as their parent.
- Every final event retains the audit event's ID. The review command below prints each ID and whether delivery finished.
- A separate deliberately denied handoff has run ID `470d49370c5a47a7b95cf1715b629e40` and trace ID `4a8b0926407b436babb9b63a2b01baea`. It produced a durable `handoff` denial with `RESOURCE_DENIED`, three audit rows, and three matching final events. The demo database still has only the earlier one purchase and one ledger entry.

```sh
.venv/bin/python scripts/show_step4_evidence.py --run-id e2796c72c77c4b57876dfb4904bbcfc0
.venv/bin/python scripts/show_step4_evidence.py --run-id 470d49370c5a47a7b95cf1715b629e40
```

## Failure and replay checks

The focused SQLite checks verify a durable denied handoff with no charge, linked buyer and researcher spans, and a worker exception before commit followed by replay. The PostgreSQL checks verify the same denied handoff and terminate a worker process after its first final-event insert, before commit. PostgreSQL rolls the transaction back; a later delivery writes the pending rows. Clearing the delivery marker and replaying them leaves one final row per event ID.

Run `.venv/bin/python scripts/run_step4_denied.py` to create another deliberate handoff denial without spending the demo budget, then run `.venv/bin/python scripts/deliver_outbox.py` to deliver it.

```sh
ACS_TEST_POSTGRES_DSN='dbname=agent_commerce_security_test' .venv/bin/python -m unittest discover -s tests -v
```

All 41 tests passed in the final local run. The PostgreSQL checks reset only the dedicated `agent_commerce_security_test` database. The named review run remains in `agent_commerce_security_demo` until that demo database is reset.

## Practical limits

The final event sink is a table in the same local database. This demonstrates transactional outbox behavior and safe replay; it does not test an external event service, network partitions, cross-system acknowledgment, retention policy, or production load. The purchase uses a fictional budget and ledger. The model-driven paid path has not been shown to succeed consistently with a live model; this run used fixture replay.
