# Step 6 verification record

The [interview script](../scripts/demo_step6.py), [setup and talk track](demo-guide.md), and [architecture image](architecture.svg) form the Step 6 package. The [sample JSON](../artifacts/step6-demo-sample.json) is one default replay run; its random IDs are examples, not fixed expected values.

The [interactive HTML visualizer](demo-visualizer.html) uses a labeled illustrative sample, accepts the real JSON output, and can request a fresh isolated run from the [loopback server](../scripts/serve_demo_ui.py).

| Check performed locally | Result |
| --- | --- |
| Package-free demo on temporary SQLite | PASS: free task 0 charges; paid task 1 mock charge and 0 cents remaining; over-scoped handoff denied; retry kept one charge; 23 audit IDs and 23 final event IDs after injected delivery failure and replay. |
| Dedicated `agent_commerce_security_interview` PostgreSQL demo | PASS with the same free, paid, denied, retry, and 23/23 event checks. |
| Optional Ollama `qwen3:1.7b` demo | PASS: free injected-text task completed without an additional charge; answer origin was `runtime_sourced_fallback`; 35/35 events delivered after replay. |
| Clean-directory copy of checkout | Fixture validation, default demo, and package-free unit tests all exited 0 without the existing virtual environment or local data. |
| Full local test suite | 52 tests passed with dedicated PostgreSQL test database. |
| Fast PostgreSQL security controls | 19/19 cases and 30/30 repeated stress cases passed. |
| Public-file check over tracked and new files | 60 files checked; no matching credential or local-data path. |
| Architecture image | Rendered to PNG locally and inspected for readable labels and flow. |
| Loopback demo UI server | Served the HTML with a per-process token; authenticated POST returned PASS with 11 paid trace events and 23 final events; missing token returned HTTP 403. |
| HTML JavaScript | Passed `node --check` syntax validation. Browser visual inspection was unavailable because the browser permission policy declined access to the local page. |

The [CI workflow](../.github/workflows/ci.yml) was syntax-checked locally, but it has **not run on GitHub** while these Step 6 files remain uncommitted. Its PostgreSQL service and action setup still need the first remote CI run for final confirmation. The secret scanner catches selected high-confidence patterns; it cannot prove that every sensitive value is absent.

The walkthrough uses deterministic replay for stable purchase and recovery evidence. The optional Ollama segment is a real model run, but its accepted final answer in this measurement was assembled by the runtime from sourced catalog facts. The injected worker failure is an exception before transaction commit; the PostgreSQL integration suite separately tests termination of an actual worker process. The 3–5 minute timing in the guide includes the presenter's explanation; the deterministic command itself finishes much faster.
