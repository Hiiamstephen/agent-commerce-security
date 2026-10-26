"""Security event trace, denial, and delivery evidence on the local store."""

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_commerce_security.audit import deliver_outbox
from agent_commerce_security.commerce import CommerceService, Store, TokenAuthority
from agent_commerce_security.runtime import Action, ReplayModel, Runtime, load_fixture


SEED = load_fixture("seed.json")
TASKS = {task["task_id"]: task for task in load_fixture("tasks.json")["tasks"]}


class InvalidHandoffModel:
    def choose(self, role, view, observations):
        return Action("handoff", {"objective": "Compare suppliers", "item_ids": ["not_in_task"]})


class Step4Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = Store(Path(temp.name) / "audit.sqlite3")
        self.store.initialize(SEED)
        self.authority = TokenAuthority(b"0123456789abcdef0123456789abcdef")
        self.token = self.authority.issue("user_alice", "tenant_acme", SEED["users"][0]["scopes"])
        self.service = CommerceService(self.store, self.authority, SEED["policy"])

    def test_trace_links_both_agents_and_atomic_purchase_event(self):
        task = TASKS["task_paid_needed"]
        result = Runtime(SEED, ReplayModel(task), commerce=self.service, bearer_token=self.token).run(task)
        self.assertEqual(result["status"], "complete")
        with self.store.connect() as connection:
            rows = connection.execute("SELECT * FROM audit_events WHERE run_id = ?", (result["run_id"],)).fetchall()
            purchases = connection.execute("SELECT COUNT(*) AS n FROM purchases").fetchone()["n"]
            queued = connection.execute("SELECT COUNT(*) AS n FROM outbox").fetchone()["n"]
        events = [dict(row) for row in rows]
        self.assertEqual(purchases, 1)
        self.assertEqual(queued, len(events))
        self.assertEqual({event["trace_id"] for event in events}, {result["events"][0]["trace_id"]})
        handoff = next(event for event in events if event["action"] == "handoff" and event["decision"] == "allow")
        returned = next(event for event in events if event["action"] == "return" and event["decision"] == "allow")
        self.assertEqual(returned["parent_span_id"], handoff["span_id"])
        researcher = [event for event in events if event["role"] == "researcher"]
        self.assertTrue(researcher)
        self.assertTrue(all(event["parent_span_id"] == handoff["span_id"] for event in researcher))
        purchase = next(event for event in events if event["action"] == "purchase_service" and event["decision"] == "allow")
        self.assertEqual(purchase["parent_span_id"], returned["span_id"])
        runtime_purchase = next(event for event in result["events"] if event["action"] == "purchase_service")
        self.assertEqual(purchase["span_id"], runtime_purchase["span_id"])

    def test_denied_handoff_is_durable_and_has_no_charge(self):
        task = TASKS["task_free_sufficient"]
        result = Runtime(SEED, InvalidHandoffModel(), commerce=self.service, bearer_token=self.token).run(task)
        self.assertEqual(result["status"], "denied")
        with self.store.connect() as connection:
            denied = connection.execute("SELECT * FROM audit_events WHERE run_id = ? AND action = 'handoff' "
                                        "AND decision = 'deny'", (result["run_id"],)).fetchone()
            charges = connection.execute("SELECT COUNT(*) AS n FROM mock_ledger").fetchone()["n"]
        self.assertIsNotNone(denied)
        self.assertEqual(denied["reason_code"], "RESOURCE_DENIED")
        self.assertEqual(charges, 0)

    def test_failure_before_delivery_commit_then_replay(self):
        quote = self.service.quote(self.token, "service_reliability_report")
        self.service.purchase(self.token, quote["quote_id"], "step4_delivery")

        def crash(_event_id):
            raise RuntimeError("simulated worker crash")

        with self.assertRaisesRegex(RuntimeError, "simulated worker crash"):
            deliver_outbox(self.store, after_insert=crash)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM outbox WHERE delivered_at IS NULL").fetchone()["n"], 2)
        self.assertEqual(deliver_outbox(self.store), 2)
        with self.store.connect() as connection:
            connection.execute("UPDATE outbox SET delivered_at = NULL")
        self.assertEqual(deliver_outbox(self.store), 2)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], 2)

    def test_conflicting_final_event_is_not_acknowledged(self):
        self.service.quote(self.token, "service_reliability_report")
        self.assertEqual(deliver_outbox(self.store), 1)
        with self.store.connect() as connection:
            connection.execute("UPDATE security_events SET payload_json = '{}'")
            connection.execute("UPDATE outbox SET delivered_at = NULL")
        with self.assertRaisesRegex(ValueError, "event ID conflicts"):
            deliver_outbox(self.store)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM outbox WHERE delivered_at IS NULL").fetchone()["n"], 1)


if __name__ == "__main__":
    unittest.main()
