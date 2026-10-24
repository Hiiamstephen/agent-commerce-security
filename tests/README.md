# Tests to add in later milestones

The first tests will cover per-agent tool allowlists, authorization at both handoff directions and at each tool call, context isolation, quote revalidation, idempotent mock purchases, and outbox replay. The evaluation harness will also run the scenario fixtures in `fixtures/tasks.json`.

Step 2 adds `test_step2.py` for the bounded runtime, role allowlists, handoff and return checks, cross-tenant denial, scope checks, and the purchase stub. Run `python3 -m unittest discover -s tests -v`. These are deterministic checks with fixture identities and in-memory trace events; they do not prove model reliability, persistent audit delivery, or purchase security.
