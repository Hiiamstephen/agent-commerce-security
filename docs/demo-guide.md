# Demo and setup guide

This is a **synthetic local demo**. No real purchase, customer record, or external security event is involved. The script prints run IDs and evidence counts; IDs vary on every run.

## One-minute fresh-checkout quickstart

From a terminal with Python 3.13 or newer:

```sh
git clone https://github.com/Hiiamstephen/agent-commerce-security.git
cd agent-commerce-security
python3 scripts/validate_fixtures.py
python3 scripts/demo_step6.py
```

The default walkthrough needs no Python packages, PostgreSQL, or Ollama. It creates a temporary SQLite database and an ephemeral signing key, then removes both on exit. It does not touch `local-data/` or reset the persistent demo database. Expect `Step 6 demo: PASS`, zero charges for free research, one 50-cent mock charge for the paid task, `RESOURCE_DENIED` for the over-scoped handoff, one charge after a same-request retry, and equal audit/final-event counts after replay.

Run `python3 scripts/demo_step6.py --json` for machine-readable check results. A nonzero exit means at least one check failed.

## Interactive visual walkthrough

Open [demo-visualizer.html](demo-visualizer.html) directly to explore a clearly labeled illustrative run. Use the stage buttons or arrow keys to see the buyer/researcher handoff, mock budget change, denial, retry, and event replay. You can load an actual CLI result with **Import demo JSON**:

```sh
python3 scripts/demo_step6.py --json > /tmp/agent-commerce-demo.json
```

To enable **Run fresh local demo** inside the page, start the optional loopback server and open the printed URL:

```sh
python3 scripts/serve_demo_ui.py
# open http://127.0.0.1:8765/
```

Each click runs the same isolated replay as the CLI in a new temporary SQLite database. The server binds only to `127.0.0.1`, uses a per-process request token, and does not expose a real payment API. Stop it with Ctrl-C. The browser page is a visualization of the Python result; it does not grant the model additional tools or permissions.

## Optional PostgreSQL and local model

For the database-backed version on macOS, install [PostgreSQL 16 via Homebrew](https://formulae.brew.sh/formula/postgresql%4016) and create a database named **exactly** `agent_commerce_security_interview` once:

```sh
brew install postgresql@16
brew services start postgresql@16
python3 -m venv .venv
.venv/bin/python -m pip install --requirement requirements-dev.txt
"$(brew --prefix postgresql@16)/bin/createdb" agent_commerce_security_interview
.venv/bin/python scripts/demo_step6.py --postgres-dsn 'dbname=agent_commerce_security_interview'
```

The script refuses any other database name. Each run clears only this dedicated interview database and reloads the fictional fixture. It leaves `agent_commerce_security_demo`, test databases, and signing keys untouched.

To include a **real local model** in the walkthrough, install and start [Ollama for macOS](https://ollama.com/download/mac), pull the model once, then add `--live-model`:

```sh
ollama pull qwen3:1.7b
python3 scripts/demo_step6.py --live-model qwen3:1.7b
```

The model segment asks the two roles to handle an injected seller description in a free task. It runs after the deterministic purchase and must leave the charge count at one. The result prints `answer origin`; `runtime_sourced_fallback` means the runtime assembled the final free answer from validated catalog data after the model did not produce an accepted answer. The live path is optional because local model speed and output vary. The replay path is the reliable interview fallback and must be described as fixture-driven.

## 3–5 minute presentation

Open the [architecture image](architecture.svg) and run the default command, or include `--live-model qwen3:1.7b` when Ollama is ready.

| Time | Show | Explain |
| --- | --- | --- |
| 0:00–0:45 | Architecture image | Two roles share one task. The researcher has only a read tool; trusted code gates handoff, returns, and every tool call. The token stays out of model context. |
| 0:45–1:45 | Output lines 1–2 | Free facts answer one task without spending. The error-rate question needs the approved synthetic report. The buyer proposes a quote/purchase; policy checks the canonical quote, seller, scope, task grant, risk limit, and budget before one mock charge. |
| 1:45–2:30 | Output line 3 and trace line | An over-scoped handoff is denied with `RESOURCE_DENIED`. The paid trace contains one trace ID and linked buyer/researcher spans. A model proposal does not grant itself permission. |
| 2:30–3:30 | Output lines 4 and 5/6 | Retrying the same request returns the same receipt and keeps one charge. A deliberate failure during outbox delivery rolls back; delivery and replay leave one final security event per ID. |
| 3:30–5:00 | Optional Ollama line and [measured evaluation](step5-results.md) | Label real model and fixture results separately. Mention 19 control scenarios, the 12-payload live attack corpus, the answer fallback, and one limitation below. |

Short architecture answer: “The buyer may propose actions, while a read-only researcher supplies sourced facts. Trusted gates keep user, tenant, task, and role authority outside model output. A mock purchase checks a stored quote and budget in one transaction, and an outbox links allowed and denied decisions to security events.”

## What each result proves

- **Free task:** the fixture-driven buyer/researcher path used catalog sources and made no mock charge.
- **Paid task:** exactly one purchase and ledger row spent 50 synthetic cents; the answer came from the purchased report and was assembled by the runtime.
- **Denied handoff:** a deliberately invalid model action was rejected without adding a charge.
- **Retry:** the same request ID returned the first receipt; no second ledger entry appeared.
- **Failure/replay:** the script injects an exception after inserting a final event but before commit, then retries and replays delivery. A separate PostgreSQL test kills an actual worker process before commit.
- **Live model, if requested:** a real Ollama adapter proposed actions. Its final answer origin is printed; completion does not automatically mean the model authored the answer.

The [security benchmark contract](security-benchmark-contract.md) defines the larger test suites and release gates. This interview demo is a concise explanation of selected controls, not a production security certification. The identity provider, payment, and event sink are all local or simulated.

## CI and public-file checks

The [CI workflow](../.github/workflows/ci.yml) runs on push and pull request. It checks tracked files for likely credentials and local data, validates fixtures, runs the fresh-state demo, runs SQLite/PostgreSQL tests, and runs the fast PostgreSQL control benchmark. It does **not** run Ollama in CI.

Run the same checks locally:

```sh
python3 scripts/check_public.py
python3 scripts/validate_fixtures.py
python3 scripts/demo_step6.py --json
ACS_TEST_POSTGRES_DSN='dbname=agent_commerce_security_test' .venv/bin/python -m unittest discover -s tests -q
```

`check_public.py` is a high-confidence repository scan, not a guarantee that all sensitive material is absent. Review changed files and generated artifacts before publishing. The test database command clears only the dedicated `agent_commerce_security_test` database.
