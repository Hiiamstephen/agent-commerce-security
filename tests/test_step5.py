"""Regression for the paid-source failure found by the live evaluation."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agent_commerce_security.evaluation import CaseContext, SEED, TASKS, answer_checks, case_free_task_spend
from agent_commerce_security.runtime import Action, ReplayModel, Runtime, catalog_summary


class FreeFactsOnlyModel(ReplayModel):
    def choose(self, role, view, observations):
        if role == "buyer" and observations:
            findings = observations[0]["result"]["findings"]
            return Action("finish", {"answer": catalog_summary(findings),
                                     "sources": [item["source_id"] for item in findings]})
        return super().choose(role, view, observations)


class Step5Tests(unittest.TestCase):
    def test_evaluator_rejects_citations_without_correct_facts(self):
        paid = {"answer": "supplier_northstar is the cheapest", "sources": ["paid_report_demo_v1"],
                "receipt": {"report_id": "report_reliability_v1", "amount_minor": 50, "remaining_minor": 0}}
        self.assertFalse(answer_checks("task_paid_needed", paid)["exact_runtime_fact_answer"])
        free = {"answer": "All suppliers are excellent", "sources": [item["source_id"]
                for item in SEED["catalog_items"]]}
        self.assertFalse(answer_checks("task_free_sufficient", free)["exact_runtime_fact_answer"])

    def test_evaluator_rejects_fact_swaps_and_contradictions(self):
        from agent_commerce_security.evaluation import ANSWER_ORACLE
        expected = ANSWER_ORACLE["task_free_sufficient"]
        swapped = expected["answer"].replace("100/minute", "999/minute")
        answer = {"answer": swapped, "sources": expected["sources"]}
        self.assertFalse(answer_checks("task_free_sufficient", answer)["exact_runtime_fact_answer"])
        answer = {"answer": expected["answer"] + " Northstar is not in the US.",
                  "sources": expected["sources"]}
        self.assertFalse(answer_checks("task_free_sufficient", answer)["exact_runtime_fact_answer"])
        answer = {"answer": expected["answer"], "sources": expected["sources"],
                  "response_mode": "model"}
        self.assertFalse(answer_checks("task_free_sufficient", answer)["model_prose_reviewed"])

    def test_paid_question_cannot_finish_with_only_free_facts(self):
        context = CaseContext()
        self.addCleanup(context.close)
        task = TASKS["task_paid_needed"]
        result = Runtime(SEED, FreeFactsOnlyModel(task), commerce=context.service,
                         bearer_token=context.alice).run(task)
        self.assertEqual(result["status"], "denied")
        self.assertTrue(any(event["reason_code"] == "PAID_SOURCE_REQUIRED" for event in result["events"]))
        self.assertEqual(context.counts()["charges"], 0)

    def test_free_task_model_spend_proposal_is_denied(self):
        context = CaseContext()
        self.addCleanup(context.close)
        result, security, _ = case_free_task_spend(context)
        self.assertEqual(result["reason_code"], "TASK_PURCHASE_DENIED")
        self.assertTrue(all(security.values()))

    def test_database_oracle_detects_tampered_budget_and_event(self):
        from agent_commerce_security.audit import deliver_outbox
        context = CaseContext()
        self.addCleanup(context.close)
        context.runtime("task_free_sufficient")
        deliver_outbox(context.store)
        self.assertTrue(all(context.database_invariants().values()))
        with context.store.connect() as connection:
            connection.execute("UPDATE budgets SET remaining_minor = 49 WHERE user_id = 'user_alice'")
            connection.execute("UPDATE security_events SET payload_json = '{}' WHERE event_id = "
                               "(SELECT event_id FROM security_events LIMIT 1)")
        checks = context.database_invariants()
        self.assertFalse(checks["budget_equals_ledger"])
        self.assertFalse(checks["event_payloads_match"])


if __name__ == "__main__":
    unittest.main()
