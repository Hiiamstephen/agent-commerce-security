"""Repeatable interview demo: free research, one mock purchase, denial, retry, event replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.audit import deliver_outbox
from agent_commerce_security.commerce import CommerceService, PostgresStore, Store, TokenAuthority
from agent_commerce_security.runtime import Action, OllamaModel, ReplayModel, Runtime, load_fixture


class OverScopedHandoff:
    def choose(self, role, view, observations):
        return Action("handoff", {"objective": "Read an item outside this task",
                                  "item_ids": ["supplier_not_in_task"]})


def prepare_store(seed: dict, postgres_dsn: str | None, temporary: str):
    if postgres_dsn is None:
        store = Store(Path(temporary) / "interview.sqlite3")
        store.initialize(seed)
        return store, "temporary SQLite"
    store = PostgresStore(postgres_dsn)
    with store.connect() as connection:
        name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
    if name != "agent_commerce_security_interview":
        raise ValueError("refusing to reset a database other than agent_commerce_security_interview")
    store.initialize(seed)
    with store.connect() as connection:
        connection.execute("TRUNCATE security_events, outbox, audit_events, mock_ledger, purchases, quotes, "
                           "budgets, paid_reports, services, sellers, demo_users, tenants CASCADE")
    store.initialize(seed)
    return store, "dedicated PostgreSQL interview database"


def snapshot(store) -> dict:
    with store.connect() as connection:
        def count(table):
            return connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

        return {"purchases": count("purchases"), "charges": count("mock_ledger"),
                "audit_events": count("audit_events"), "outbox_events": count("outbox"),
                "final_events": count("security_events"),
                "pending_events": connection.execute("SELECT COUNT(*) AS n FROM outbox "
                                                     "WHERE delivered_at IS NULL").fetchone()["n"],
                "remaining_minor": connection.execute("SELECT remaining_minor FROM budgets "
                                                      "WHERE user_id = 'user_alice'").fetchone()["remaining_minor"]}


def linked_trace(store, run_id: str) -> dict:
    with store.connect() as connection:
        rows = connection.execute("SELECT role, action, decision, reason_code, span_id, parent_span_id, trace_id "
                                  "FROM audit_events WHERE run_id = ? ORDER BY occurred_at, event_id",
                                  (run_id,)).fetchall()
    span_ids = {row["span_id"] for row in rows}
    return {"event_count": len(rows), "trace_ids": sorted({row["trace_id"] for row in rows}),
            "parent_links": sum(row["parent_span_id"] in span_ids for row in rows
                                if row["parent_span_id"] is not None),
            "events": [{"role": row["role"], "action": row["action"],
                        "decision": row["decision"], "reason_code": row["reason_code"],
                        "span_id": row["span_id"], "parent_span_id": row["parent_span_id"]}
                       for row in rows],
            "handoff_allowed": any(row["action"] == "handoff" and row["decision"] == "allow"
                                   for row in rows),
            "researcher_return_allowed": any(row["role"] == "researcher" and row["action"] == "return"
                                               and row["decision"] == "allow" for row in rows)}


def crash(_event_id: str):
    raise RuntimeError("deliberate worker crash before commit")


def run_demo(postgres_dsn: str | None = None, live_model: str | None = None) -> dict:
    seed = load_fixture("seed.json")
    tasks = {item["task_id"]: item for item in load_fixture("tasks.json")["tasks"]}
    with tempfile.TemporaryDirectory(prefix="agent-commerce-interview-") as temporary:
        store, backend = prepare_store(seed, postgres_dsn, temporary)
        authority = TokenAuthority(secrets.token_bytes(32))
        alice = seed["users"][0]
        token = authority.issue(alice["user_id"], alice["tenant_id"], alice["scopes"])
        service = CommerceService(store, authority, seed["policy"])

        free_task = tasks["task_free_sufficient"]
        free = Runtime(seed, ReplayModel(free_task), commerce=service, bearer_token=token).run(free_task)
        after_free = snapshot(store)
        free_trace = linked_trace(store, free["run_id"])

        paid_task = tasks["task_paid_needed"]
        paid_runtime = Runtime(seed, ReplayModel(paid_task), commerce=service, bearer_token=token)
        paid = paid_runtime.run(paid_task)
        after_paid = snapshot(store)
        receipt = paid.get("answer", {}).get("receipt", {})
        paid_trace = linked_trace(store, paid["run_id"])

        denied = Runtime(seed, OverScopedHandoff(), commerce=service,
                         bearer_token=token).run(free_task)
        after_denied = snapshot(store)
        denied_trace = linked_trace(store, denied["run_id"])

        replay = service.purchase(token, receipt.get("quote_id", ""), paid_runtime.purchase_request_id)
        after_retry = snapshot(store)

        live = None
        if live_model:
            live_task = tasks["task_seller_injection"]
            live_result = Runtime(seed, OllamaModel(live_model), max_seconds=180,
                                  commerce=service, bearer_token=token).run(live_task)
            live = {"model": live_model, "run_id": live_result["run_id"],
                    "status": live_result["status"], "reason_code": live_result.get("reason_code"),
                    "answer_origin": live_result.get("answer", {}).get("response_mode"),
                    "charges_after": snapshot(store)["charges"]}

        crashed = False
        try:
            deliver_outbox(store, after_insert=crash)
        except RuntimeError:
            crashed = True
        after_crash = snapshot(store)
        first_delivery = deliver_outbox(store)
        after_delivery = snapshot(store)
        with store.connect() as connection:
            connection.execute("UPDATE outbox SET delivered_at = NULL")
        replay_delivery = deliver_outbox(store)
        after_event_replay = snapshot(store)

        checks = {
            "free_complete_without_spend": free["status"] == "complete" and after_free["charges"] == 0,
            "paid_complete_one_charge": paid["status"] == "complete" and after_paid["charges"] == 1
                                        and after_paid["purchases"] == 1 and after_paid["remaining_minor"] == 0,
            "paid_handoff_and_return_linked": paid_trace["handoff_allowed"]
                                               and paid_trace["researcher_return_allowed"]
                                               and paid_trace["parent_links"] >= 1,
            "over_scoped_handoff_denied": denied.get("reason_code") == "RESOURCE_DENIED"
                                          and after_denied["charges"] == 1,
            "same_request_one_charge": replay.get("idempotent_replay") is True
                                       and replay["purchase_id"] == receipt.get("purchase_id")
                                       and after_retry["charges"] == 1,
            "worker_crash_rolled_back": crashed and after_crash["final_events"] == 0,
            "events_delivered_once": first_delivery == after_delivery["audit_events"]
                                     and after_delivery["final_events"] == after_delivery["audit_events"]
                                     and after_delivery["pending_events"] == 0,
            "event_replay_deduplicated": replay_delivery == after_delivery["audit_events"]
                                         and after_event_replay["final_events"] == after_delivery["final_events"]
                                         and after_event_replay["pending_events"] == 0,
        }
        if live is not None:
            checks["live_model_safe_and_complete"] = live["status"] == "complete" and live["charges_after"] == 1
        return {"status": "PASS" if all(checks.values()) else "FAIL", "backend": backend,
                "mode": "live_plus_replay" if live_model else "fixture_replay",
                "checks": checks,
                "free": {"run_id": free["run_id"], "status": free["status"],
                         "sources": free.get("answer", {}).get("sources"), "charges": after_free["charges"],
                         "trace": free_trace},
                "paid": {"run_id": paid["run_id"], "status": paid["status"],
                         "answer": paid.get("answer", {}).get("answer"),
                         "source": paid.get("answer", {}).get("sources"),
                         "purchase_id": receipt.get("purchase_id"), "amount_minor": receipt.get("amount_minor"),
                         "remaining_minor": after_paid["remaining_minor"], "trace": paid_trace},
                "denied": {"run_id": denied["run_id"], "reason_code": denied.get("reason_code"),
                           "charges": after_denied["charges"], "trace": denied_trace},
                "retry": {"same_purchase_id": replay["purchase_id"] == receipt.get("purchase_id"),
                          "charges": after_retry["charges"]},
                "delivery": {"crash_rolled_back": crashed, "first_batch": first_delivery,
                             "replay_batch": replay_delivery, "audit_events": after_event_replay["audit_events"],
                             "final_events": after_event_replay["final_events"]},
                "live": live}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-dsn", help="Reset only agent_commerce_security_interview")
    parser.add_argument("--live-model", help="Run one real local Ollama task after the deterministic cases")
    parser.add_argument("--json", action="store_true", help="Machine-readable summary")
    args = parser.parse_args()
    result = run_demo(args.postgres_dsn, args.live_model)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Step 6 demo: {result['status']} ({result['backend']}; {result['mode']})")
        print(f"1. Free research: {result['free']['status']}; charges {result['free']['charges']}")
        print(f"2. Paid report: {result['paid']['answer']}; mock charge "
              f"{result['paid']['amount_minor']} cents; budget left {result['paid']['remaining_minor']} cents")
        print(f"   Trace: {result['paid']['trace']['event_count']} events, "
              f"{result['paid']['trace']['parent_links']} parent links; run {result['paid']['run_id']}")
        print(f"3. Over-scoped handoff: {result['denied']['reason_code']}; charges remain "
              f"{result['denied']['charges']}")
        print(f"4. Same-request retry: same receipt {result['retry']['same_purchase_id']}; "
              f"charges {result['retry']['charges']}")
        if result["live"]:
            print(f"5. Ollama {result['live']['model']}: {result['live']['status']}; "
                  f"answer origin {result['live']['answer_origin']}; "
                  f"charges remain {result['live']['charges_after']}")
        delivery_step = 6 if result["live"] else 5
        print(f"{delivery_step}. Injected worker failure/replay: rollback {result['delivery']['crash_rolled_back']}; "
              f"audit {result['delivery']['audit_events']}; "
              f"final unique events {result['delivery']['final_events']}")
        if result["status"] != "PASS":
            print("Failed checks: " + ", ".join(name for name, ok in result["checks"].items() if not ok))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
