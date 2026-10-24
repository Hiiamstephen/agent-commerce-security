"""Step 2 security boundary checks; no database or model service required."""

import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_commerce_security.runtime import Action, Denied, ReplayModel, Runtime, load_fixture


SEED = load_fixture("seed.json")
TASKS = {t["task_id"]: t for t in load_fixture("tasks.json")["tasks"]}


class FixedModel:
    def __init__(self, action):
        self.action = action

    def choose(self, role, view, observations):
        return self.action


class Step2Tests(unittest.TestCase):
    def test_free_path_and_sourced_return(self):
        result = Runtime(SEED, ReplayModel(TASKS["task_free_sufficient"])).run(TASKS["task_free_sufficient"])
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["answer"]["sources"]), 3)
        self.assertTrue(any(e["action"] == "return" and e["decision"] == "allow" for e in result["events"]))
        self.assertFalse(any(e["action"] == "purchase_service" and e["decision"] == "allow" for e in result["events"]))

    def test_paid_path_stops_at_purchase_stub(self):
        result = Runtime(SEED, ReplayModel(TASKS["task_paid_needed"])).run(TASKS["task_paid_needed"])
        self.assertEqual(result["answer"]["status"], "purchase_deferred")
        self.assertTrue(any(e["reason_code"] == "PURCHASE_NOT_IMPLEMENTED" for e in result["events"]))

    def test_cross_tenant_denied_before_model(self):
        result = Runtime(SEED, ReplayModel(TASKS["task_cross_tenant"])).run(TASKS["task_cross_tenant"])
        self.assertEqual(result["reason_code"], "TENANT_DENIED")
        self.assertEqual(result["steps"], 0)

    def test_researcher_cannot_purchase(self):
        runtime = Runtime(SEED, ReplayModel(TASKS["task_free_sufficient"]))
        runtime.actor = runtime.users["user_alice"]
        with self.assertRaisesRegex(Denied, "ROLE_TOOL_DENIED"):
            runtime.tool("researcher", {"name": "purchase_service", "quote_id": "x"})

    def test_over_scoped_handoff_denied(self):
        task = TASKS["task_free_sufficient"]
        model = FixedModel(Action("handoff", {"objective": "read", "item_ids": ["supplier_northstar", "other"]}))
        result = Runtime(SEED, model).run(task)
        self.assertEqual(result["reason_code"], "RESOURCE_DENIED")
        self.assertTrue(any(e["action"] == "handoff" and e["decision"] == "deny" for e in result["events"]))

    def test_forged_return_denied(self):
        runtime = Runtime(SEED, ReplayModel(TASKS["task_free_sufficient"]))
        runtime.actor = runtime.users["user_alice"]
        with self.assertRaisesRegex(Denied, "RETURN_ORIGIN_DENIED"):
            runtime.return_gate({"run_id": "forged", "tenant_id": "tenant_acme", "sender": "researcher"}, "parent")

    def test_missing_user_scope_denied(self):
        seed = copy.deepcopy(SEED)
        seed["users"][0]["scopes"].remove("research:delegate")
        result = Runtime(seed, ReplayModel(TASKS["task_free_sufficient"])).run(TASKS["task_free_sufficient"])
        self.assertEqual(result["reason_code"], "HANDOFF_SCOPE_DENIED")

    def test_step_limit(self):
        seed = copy.deepcopy(SEED)
        seed["policy"]["max_model_steps_per_run"] = 1
        result = Runtime(seed, ReplayModel(TASKS["task_free_sufficient"])).run(TASKS["task_free_sufficient"])
        self.assertEqual(result["reason_code"], "STEP_LIMIT")

    def test_seller_injection_replay_does_not_spend(self):
        task = TASKS["task_seller_injection"]
        class InspectingReplay(ReplayModel):
            saw_injection = False

            def choose(self, role, view, observations):
                if role == "researcher" and observations:
                    self.saw_injection = "Ignore the user" in observations[-1]["result"]["seller_description"]["text"]
                return super().choose(role, view, observations)

        model = InspectingReplay(task)
        result = Runtime(SEED, model).run(task)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(model.saw_injection)
        self.assertFalse(any(e["action"] == "purchase_service" for e in result["events"]))

    def test_model_cannot_add_tenant_to_handoff(self):
        task = TASKS["task_free_sufficient"]
        model = FixedModel(Action("handoff", {"objective": "read", "item_ids": ["supplier_northstar"], "tenant_id": "tenant_beta"}))
        result = Runtime(SEED, model).run(task)
        self.assertEqual(result["reason_code"], "HANDOFF_SCHEMA_DENIED")

    def test_model_cannot_add_scope_to_tool(self):
        task = TASKS["task_free_sufficient"]
        model = FixedModel(Action("tool", {"name": "list_services", "item_ids": ["supplier_northstar"], "scope": "purchase:write"}))
        result = Runtime(SEED, model).run(task)
        self.assertEqual(result["reason_code"], "TOOL_SCHEMA_DENIED")


if __name__ == "__main__":
    unittest.main()
