"""Print a compact audit trace and delivery state for review."""

import argparse
import json

from run_step3 import make_store


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", help="Run to inspect; defaults to the most recent recorded run")
    args = parser.parse_args()
    store = make_store()
    with store.connect() as connection:
        run_id = args.run_id
        if run_id is None:
            latest = connection.execute("SELECT run_id FROM audit_events WHERE run_id IS NOT NULL "
                                        "ORDER BY occurred_at DESC, event_id DESC LIMIT 1").fetchone()
            if latest is None:
                parser.error("no recorded run found")
            run_id = latest["run_id"]
        rows = connection.execute(
            "SELECT a.event_id, a.trace_id, a.span_id, a.parent_span_id, a.role, a.action, a.decision, "
            "a.reason_code, a.occurred_at, o.delivered_at, s.event_id AS final_event_id "
            "FROM audit_events a JOIN outbox o ON o.event_id = a.event_id "
            "LEFT JOIN security_events s ON s.event_id = a.event_id "
            "WHERE a.run_id = ? ORDER BY a.occurred_at, a.event_id", (run_id,)
        ).fetchall()
    if not rows:
        parser.error("run ID has no audit events")
    events = [{"event_id": row["event_id"], "span_id": row["span_id"],
               "parent_span_id": row["parent_span_id"],
               "role": row["role"], "action": row["action"], "decision": row["decision"],
               "reason_code": row["reason_code"], "delivered": row["delivered_at"] is not None,
               "final_event_id": row["final_event_id"]} for row in rows]
    print(json.dumps({"run_id": run_id, "trace_id": rows[0]["trace_id"],
                      "audit_count": len(events),
                      "final_count": sum(event["final_event_id"] is not None for event in events),
                      "events": events}, indent=2))


if __name__ == "__main__":
    main()
