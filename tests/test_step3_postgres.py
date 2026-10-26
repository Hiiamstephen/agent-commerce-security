"""Integration checks against an explicitly dedicated PostgreSQL test database."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_commerce_security.commerce import CommerceService, PostgresStore, SecurityError, TokenAuthority
from agent_commerce_security.audit import deliver_outbox
from agent_commerce_security.runtime import Action, Runtime, load_fixture


SEED = load_fixture("seed.json")


class PostgresStep3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dsn = os.environ.get("ACS_TEST_POSTGRES_DSN")
        if not dsn:
            raise unittest.SkipTest("set ACS_TEST_POSTGRES_DSN to run PostgreSQL integration checks")
        cls.store = PostgresStore(dsn)
        with cls.store.connect() as connection:
            name = connection.execute("SELECT current_database() AS name").fetchone()["name"]
        if name != "agent_commerce_security_test":
            raise RuntimeError("integration checks require database agent_commerce_security_test")

    def setUp(self):
        self.store.initialize(SEED)
        with self.store.connect() as connection:
            connection.execute("TRUNCATE security_events, outbox, audit_events, mock_ledger, purchases, quotes, "
                               "budgets, paid_reports, services, sellers, demo_users, tenants RESTART IDENTITY CASCADE")
        self.store.initialize(SEED)
        now = datetime.now(timezone.utc)
        self.authority = TokenAuthority(b"0123456789abcdef0123456789abcdef", lambda: now)
        self.service = CommerceService(self.store, self.authority, SEED["policy"], lambda: now)
        self.alice = self.authority.issue("user_alice", "tenant_acme", SEED["users"][0]["scopes"])

    def counts(self):
        with self.store.connect() as connection:
            return (
                connection.execute("SELECT COUNT(*) AS n FROM purchases").fetchone()["n"],
                connection.execute("SELECT COUNT(*) AS n FROM mock_ledger").fetchone()["n"],
                connection.execute("SELECT remaining_minor FROM budgets WHERE user_id = ?", ("user_alice",)).fetchone()["remaining_minor"],
            )

    def test_atomic_purchase_and_idempotent_retry(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        first = self.service.purchase(self.alice, quote["quote_id"], "same_request")
        replay = self.service.purchase(self.alice, quote["quote_id"], "same_request")
        self.assertEqual(first["purchase_id"], replay["purchase_id"])
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_parallel_purchases_cannot_overspend(self):
        quotes = [self.service.quote(self.alice, "service_reliability_report") for _ in range(2)]

        def buy(index):
            try:
                self.service.purchase(self.alice, quotes[index]["quote_id"], f"parallel_{index}")
                return "allow"
            except SecurityError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(buy, range(2)))
        self.assertEqual(sorted(outcomes), ["BUDGET_EXCEEDED", "allow"])
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_tenant_and_scope_denied(self):
        wrong_tenant = self.authority.issue("user_alice", "tenant_beta", ["quote:read"])
        with self.assertRaises(SecurityError) as denied:
            self.service.quote(wrong_tenant, "service_reliability_report")
        self.assertEqual(denied.exception.code, "TENANT_DENIED")
        quote = self.service.quote(self.alice, "service_reliability_report")
        no_purchase = self.authority.issue("user_alice", "tenant_acme", ["quote:read"])
        with self.assertRaises(SecurityError) as denied:
            self.service.purchase(no_purchase, quote["quote_id"], "no_scope")
        self.assertEqual(denied.exception.code, "USER_SCOPE_DENIED")
        self.assertEqual(self.counts(), (0, 0, 50))

    def test_outbox_retry_deduplicates_postgres_sink(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        self.service.purchase(self.alice, quote["quote_id"], "outbox_request")
        self.assertEqual(deliver_outbox(self.store), 2)
        with self.store.connect() as connection:
            connection.execute("UPDATE outbox SET delivered_at = NULL")
        self.assertEqual(deliver_outbox(self.store), 2)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], 2)
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM mock_ledger").fetchone()["n"], 1)

    def test_worker_process_crash_rolls_back_then_replays_once(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        self.service.purchase(self.alice, quote["quote_id"], "worker_crash")
        code = ("import os, sys\n"
                "from agent_commerce_security.audit import deliver_outbox\n"
                "from agent_commerce_security.commerce import PostgresStore\n"
                "deliver_outbox(PostgresStore(sys.argv[1]), after_insert=lambda _: os._exit(77))\n")
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        crashed = subprocess.run([sys.executable, "-c", code, self.store.dsn],
                                 env=environment, capture_output=True, timeout=10, check=False)
        self.assertEqual(crashed.returncode, 77, crashed.stderr.decode())
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM outbox WHERE delivered_at IS NULL").fetchone()["n"], 2)
        self.assertEqual(deliver_outbox(self.store), 2)
        with self.store.connect() as connection:
            connection.execute("UPDATE outbox SET delivered_at = NULL")
        self.assertEqual(deliver_outbox(self.store), 2)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], 2)

    def test_denied_handoff_is_durable_in_postgres(self):
        class InvalidHandoff:
            def choose(self, role, view, observations):
                return Action("handoff", {"objective": "Read outside task", "item_ids": ["not_in_task"]})

        task = next(task for task in load_fixture("tasks.json")["tasks"]
                    if task["task_id"] == "task_free_sufficient")
        result = Runtime(SEED, InvalidHandoff(), commerce=self.service, bearer_token=self.alice).run(task)
        self.assertEqual(result["reason_code"], "RESOURCE_DENIED")
        with self.store.connect() as connection:
            denied = connection.execute("SELECT * FROM audit_events WHERE run_id = ? AND action = 'handoff' "
                                        "AND decision = 'deny'", (result["run_id"],)).fetchone()
            self.assertIsNotNone(denied)
            self.assertEqual(denied["reason_code"], "RESOURCE_DENIED")
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM mock_ledger").fetchone()["n"], 0)


if __name__ == "__main__":
    unittest.main()
