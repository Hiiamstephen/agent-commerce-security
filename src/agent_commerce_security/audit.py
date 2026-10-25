"""Durable, minimal audit records and transactional outbox delivery."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import uuid4


def new_event(role: str, action: str, decision: str, reason_code: str, *,
              run_id: str | None = None, trace_id: str | None = None,
              span_id: str | None = None, parent_span_id: str | None = None,
              tenant_id: str | None = None, user_id: str | None = None) -> dict:
    return {"event_id": uuid4().hex, "run_id": run_id, "trace_id": trace_id or uuid4().hex,
            "span_id": span_id or uuid4().hex, "parent_span_id": parent_span_id,
            "tenant_id": tenant_id, "user_id": user_id, "role": role, "action": action,
            "decision": decision, "reason_code": reason_code,
            "occurred_at": datetime.now(timezone.utc).isoformat()}


def append_event(connection, event: dict) -> None:
    """Call inside the caller's transaction so audit and business writes commit together."""
    fields = ("event_id", "run_id", "trace_id", "span_id", "parent_span_id", "tenant_id",
              "user_id", "role", "action", "decision", "reason_code", "occurred_at")
    connection.execute("INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       tuple(event[key] for key in fields))
    connection.execute("INSERT INTO outbox VALUES (?, ?, ?, ?, ?)",
                       (event["event_id"], "security.decision", json.dumps(event, sort_keys=True),
                        event["occurred_at"], None))


def record_event(store, event: dict) -> None:
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            append_event(connection, event)
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def deliver_outbox(store, batch_size: int = 100) -> int:
    """Copy pending events to the local sink; retries cannot create duplicates."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            query = "SELECT event_id, event_type, payload_json, created_at FROM outbox WHERE delivered_at IS NULL ORDER BY created_at, event_id LIMIT ?"
            if store.is_postgres:
                query += " FOR UPDATE SKIP LOCKED"
            rows = connection.execute(query, (batch_size,)).fetchall()
            for row in rows:
                payload = json.loads(row["payload_json"])
                connection.execute("INSERT OR IGNORE INTO security_events VALUES (?, ?, ?, ?, ?)",
                                   (row["event_id"], row["event_type"], payload["trace_id"],
                                    row["created_at"], row["payload_json"]))
                connection.execute("UPDATE outbox SET delivered_at = ? WHERE event_id = ?",
                                   (datetime.now(timezone.utc).isoformat(), row["event_id"]))
            connection.commit()
            return len(rows)
        except Exception:
            connection.rollback()
            raise
