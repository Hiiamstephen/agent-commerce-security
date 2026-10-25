"""Step 3 identity, policy, transaction, and retry checks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_commerce_security.commerce import CommerceService, SecurityError, Store, TokenAuthority
from agent_commerce_security.audit import deliver_outbox
from agent_commerce_security.api import DemoAPI
from agent_commerce_security.runtime import ReplayModel, Runtime, load_fixture


SEED = load_fixture("seed.json")
TASKS = {task["task_id"]: task for task in load_fixture("tasks.json")["tasks"]}


class Step3Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 25, tzinfo=timezone.utc)
        self.clock = lambda: self.now
        self.store = Store(Path(self.temp.name) / "demo.sqlite3")
        self.store.initialize(SEED)
        self.authority = TokenAuthority(b"0123456789abcdef0123456789abcdef", self.clock)
        self.service = CommerceService(self.store, self.authority, dict(SEED["policy"]), self.clock)
        self.alice = self.authority.issue("user_alice", "tenant_acme", SEED["users"][0]["scopes"])
        self.bob = self.authority.issue("user_bob", "tenant_beta", SEED["users"][1]["scopes"])

    def assert_denied(self, code, function, *args, **kwargs):
        with self.assertRaises(SecurityError) as raised:
            function(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)

    def counts(self):
        with self.store.connect() as connection:
            return (connection.execute("SELECT COUNT(*) FROM purchases").fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM mock_ledger").fetchone()[0],
                    connection.execute("SELECT remaining_minor FROM budgets WHERE user_id = 'user_alice'").fetchone()[0])

    def test_valid_purchase_is_atomic_and_uses_server_price(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        receipt = self.service.purchase(self.alice, quote["quote_id"], "request_one")
        self.assertEqual(receipt["amount_minor"], 50)
        self.assertEqual(receipt["remaining_minor"], 0)
        self.assertEqual(receipt["report"]["sample_error_rate_percent"]["supplier_harbor"], 0.5)
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_forged_expired_and_wrong_audience_tokens(self):
        altered = self.alice[:-2] + ("AA" if self.alice[-2:] != "AA" else "BB")
        self.assert_denied("TOKEN_INVALID", self.service.quote, altered, "service_reliability_report")
        other_key = TokenAuthority(b"different-key-0123456789abcdef000000", self.clock)
        self.assert_denied("TOKEN_INVALID", self.service.quote,
                           other_key.issue("user_alice", "tenant_acme", ["quote:read"]), "service_reliability_report")
        header, payload, _ = self.alice.split(".")
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        claims["aud"] = "wrong-audience"
        changed_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
        signature = base64.urlsafe_b64encode(hmac.new(b"0123456789abcdef0123456789abcdef",
                            f"{header}.{changed_payload}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        wrong_audience = f"{header}.{changed_payload}.{signature}"
        self.assert_denied("TOKEN_INVALID", self.service.quote, wrong_audience, "service_reliability_report")
        self.now += timedelta(minutes=16)
        self.assert_denied("TOKEN_INVALID", self.service.quote, self.alice, "service_reliability_report")

    def test_wrong_tenant_scope_and_role(self):
        wrong_tenant = self.authority.issue("user_alice", "tenant_beta", ["quote:read"])
        self.assert_denied("TENANT_DENIED", self.service.quote, wrong_tenant, "service_reliability_report")
        no_purchase = self.authority.issue("user_alice", "tenant_acme", ["quote:read"])
        quote = self.service.quote(self.alice, "service_reliability_report")
        self.assert_denied("USER_SCOPE_DENIED", self.service.purchase, no_purchase, quote["quote_id"], "scope")
        self.assert_denied("ROLE_TOOL_DENIED", self.service.purchase, self.alice, quote["quote_id"], "role", agent_role="researcher")
        self.assert_denied("QUOTE_OWNER_DENIED", self.service.purchase, self.bob, quote["quote_id"], "other_user")
        self.assertEqual(self.counts(), (0, 0, 50))

    def test_quote_expiry_and_price_change(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        self.now += timedelta(seconds=301)
        self.assert_denied("QUOTE_EXPIRED", self.service.purchase, self.alice, quote["quote_id"], "expired")
        self.now -= timedelta(seconds=301)
        with self.store.connect() as connection:
            connection.execute("UPDATE services SET price_minor = 51, version = version + 1 WHERE service_id = ?",
                               ("service_reliability_report",))
        self.assert_denied("QUOTE_CHANGED", self.service.purchase, self.alice, quote["quote_id"], "changed")
        self.assertEqual(self.counts(), (0, 0, 50))

    def test_seller_risk_and_budget_denials(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        with self.store.connect() as connection:
            connection.execute("UPDATE sellers SET approved = 0 WHERE seller_id = 'seller_demo_data'")
        self.assert_denied("SELLER_BLOCKED", self.service.purchase, self.alice, quote["quote_id"], "blocked")
        with self.store.connect() as connection:
            connection.execute("UPDATE sellers SET approved = 1 WHERE seller_id = 'seller_demo_data'")
        self.service.policy["max_single_purchase_minor"] = 49
        self.assert_denied("RISK_LIMIT", self.service.purchase, self.alice, quote["quote_id"], "risk")
        self.service.policy["max_single_purchase_minor"] = 50
        with self.store.connect() as connection:
            connection.execute("UPDATE budgets SET remaining_minor = 49 WHERE user_id = 'user_alice'")
        self.assert_denied("BUDGET_EXCEEDED", self.service.purchase, self.alice, quote["quote_id"], "budget")
        self.assertEqual(self.counts(), (0, 0, 49))

    def test_retry_is_idempotent_and_changed_arguments_conflict(self):
        first_quote = self.service.quote(self.alice, "service_reliability_report")
        first = self.service.purchase(self.alice, first_quote["quote_id"], "same_request")
        self.now += timedelta(seconds=301)
        second = self.service.purchase(self.alice, first_quote["quote_id"], "same_request")
        self.assertEqual(first["purchase_id"], second["purchase_id"])
        self.assertTrue(second["idempotent_replay"])
        other_quote = self.service.quote(self.alice, "service_reliability_report")
        self.assert_denied("IDEMPOTENCY_CONFLICT", self.service.purchase,
                           self.alice, other_quote["quote_id"], "same_request")
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_same_quote_cannot_be_bought_with_new_request_id(self):
        quote = self.service.quote(self.bob, "service_reliability_report")
        self.service.purchase(self.bob, quote["quote_id"], "first")
        self.assert_denied("QUOTE_ALREADY_USED", self.service.purchase, self.bob, quote["quote_id"], "second")
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM mock_ledger WHERE user_id = 'user_bob'").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT remaining_minor FROM budgets WHERE user_id = 'user_bob'").fetchone()[0], 100)

    def test_current_scope_revocation_blocks_purchase(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        with self.store.connect() as connection:
            connection.execute("UPDATE demo_users SET scopes_json = ? WHERE user_id = 'user_alice'",
                               (json.dumps(["catalog:read", "quote:read"]),))
        self.assert_denied("USER_SCOPE_DENIED", self.service.purchase, self.alice, quote["quote_id"], "revoked")
        self.assertEqual(self.counts(), (0, 0, 50))

    def test_race_for_last_budget_creates_one_charge(self):
        quotes = [self.service.quote(self.alice, "service_reliability_report") for _ in range(2)]

        def buy(index):
            try:
                self.service.purchase(self.alice, quotes[index]["quote_id"], f"race_{index}")
                return "allow"
            except SecurityError as error:
                return error.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(buy, range(2)))
        self.assertEqual(sorted(outcomes), ["BUDGET_EXCEEDED", "allow"])
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_agent_runtime_uses_verified_identity_and_purchases(self):
        task = TASKS["task_paid_needed"]
        result = Runtime(SEED, ReplayModel(task), commerce=self.service, bearer_token=self.alice).run(task)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"]["status"], "purchased")
        self.assertEqual(result["answer"]["sources"], ["paid_report_demo_v1"])
        self.assertEqual(self.counts(), (1, 1, 0))
        forged = Runtime(SEED, ReplayModel(task), commerce=self.service, bearer_token=self.bob).run(task)
        self.assertEqual(forged["reason_code"], "USER_DENIED")

    def test_http_boundary_rejects_price_arguments_and_uses_token(self):
        app = DemoAPI(self.service, SEED["catalog_items"])

        def call(path, body, token):
            statuses = []
            data = json.dumps(body).encode()
            environ = {"REQUEST_METHOD": "POST", "PATH_INFO": path,
                       "CONTENT_TYPE": "application/json", "CONTENT_LENGTH": str(len(data)),
                       "HTTP_AUTHORIZATION": f"Bearer {token}" if token else "",
                       "wsgi.input": io.BytesIO(data)}
            response = b"".join(app(environ, lambda status, headers: statuses.append(status)))
            return statuses[0], json.loads(response)

        status, _ = call("/v1/quotes", {"service_id": "service_reliability_report"}, None)
        self.assertEqual(status, "401 Unauthorized")
        status, _ = call("/v1/quotes", {"service_id": "service_reliability_report", "price_minor": 1}, self.alice)
        self.assertEqual(status, "400 Bad Request")
        status, quote = call("/v1/quotes", {"service_id": "service_reliability_report"}, self.alice)
        self.assertEqual(status, "201 Created")
        status, receipt = call("/v1/purchases", {"quote_id": quote["quote_id"], "request_id": "api_one"}, self.alice)
        self.assertEqual(status, "201 Created")
        self.assertEqual(receipt["amount_minor"], 50)
        self.assertEqual(self.counts(), (1, 1, 0))

    def test_audit_outbox_delivery_is_replay_safe(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        self.service.purchase(self.alice, quote["quote_id"], "audit_request")
        self.assert_denied("QUOTE_ALREADY_USED", self.service.purchase, self.alice, quote["quote_id"], "new_request")
        with self.store.connect() as connection:
            queued = connection.execute("SELECT COUNT(*) AS n FROM outbox").fetchone()["n"]
            self.assertEqual(queued, 3)
        self.assertEqual(deliver_outbox(self.store), queued)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], queued)
            connection.execute("UPDATE outbox SET delivered_at = NULL")
        self.assertEqual(deliver_outbox(self.store), queued)
        with self.store.connect() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) AS n FROM security_events").fetchone()["n"], queued)
        self.assertEqual(deliver_outbox(self.store), 0)

    def test_failed_audit_rolls_back_purchase_and_budget(self):
        quote = self.service.quote(self.alice, "service_reliability_report")
        with self.store.connect() as connection:
            connection.execute("CREATE TRIGGER fail_purchase_audit BEFORE INSERT ON audit_events "
                               "WHEN NEW.action = 'purchase_service' BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.purchase(self.alice, quote["quote_id"], "failed_audit")
        self.assertEqual(self.counts(), (0, 0, 50))

    def test_runtime_decisions_are_durable(self):
        task = TASKS["task_free_sufficient"]
        result = Runtime(SEED, ReplayModel(task), commerce=self.service, bearer_token=self.alice).run(task)
        self.assertEqual(result["status"], "complete")
        with self.store.connect() as connection:
            rows = connection.execute("SELECT action, decision FROM audit_events WHERE run_id = ?", (result["run_id"],)).fetchall()
        self.assertTrue(any(row["action"] == "handoff" and row["decision"] == "allow" for row in rows))
        self.assertTrue(any(row["action"] == "list_services" and row["decision"] == "allow" for row in rows))


if __name__ == "__main__":
    unittest.main()
