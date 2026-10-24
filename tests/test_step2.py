"""Step 2 security boundary checks; no database or model service required."""

import copy
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_commerce_security.runtime import Action, Denied, OllamaModel, ReplayModel, Runtime, load_fixture


SEED = load_fixture("seed.json")
TASKS = {t["task_id"]: t for t in load_fixture("tasks.json")["tasks"]}


class FixedModel:
    def __init__(self, action):
        self.action = action

    def choose(self, role, view, observations):
        return self.action


class PrematureResearchModel:
    def choose(self, role, view, observations):
        if role == "buyer":
            if not observations:
                return Action("handoff", {"objective": "Compare free catalog facts", "item_ids": view["item_ids"]})
            return Action("finish", {"answer": "Free facts received"})
        if not observations:
            return Action("finish", {"status": "complete"})
        if not any(o.get("tool") == "list_services" for o in observations):
            return Action("tool", {"name": "list_services", "item_ids": view["item_ids"]})
        return Action("finish", {"unknowns": [], "status": "complete"})


class IncompleteBuyerModel(ReplayModel):
    def choose(self, role, view, observations):
        if role == "buyer" and observations:
            return Action("finish", {"item_ids": view["item_ids"]})
        return super().choose(role, view, observations)


class PrematureBuyerModel(ReplayModel):
    def choose(self, role, view, observations):
        if role == "buyer":
            return Action("finish", {"item_ids": view["item_ids"]})
        return super().choose(role, view, observations)


class PlaceholderBuyerModel(ReplayModel):
    def choose(self, role, view, observations):
        if role == "buyer" and observations:
            sources = [f["source_id"] for f in observations[0]["result"]["findings"]]
            return Action("finish", {"answer": "A factual comparison in sentences", "sources": sources})
        return super().choose(role, view, observations)


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

    def test_researcher_must_read_before_returning(self):
        task = TASKS["task_free_sufficient"]
        result = Runtime(SEED, PrematureResearchModel()).run(task)
        self.assertEqual(result["status"], "complete")
        self.assertTrue(any(e["reason_code"] == "RESEARCH_SOURCE_REQUIRED" for e in result["events"]))
        self.assertTrue(any(e["action"] == "return" and e["decision"] == "allow" for e in result["events"]))

    def test_incomplete_buyer_answer_uses_sourced_fallback(self):
        task = TASKS["task_free_sufficient"]
        result = Runtime(SEED, IncompleteBuyerModel(task)).run(task)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"]["response_mode"], "runtime_sourced_fallback")
        self.assertIn("rate limit 100/minute", result["answer"]["answer"])
        self.assertEqual(len(result["answer"]["sources"]), 3)
        self.assertTrue(any(e["reason_code"] == "BUYER_ANSWER_SCHEMA_DENIED" for e in result["events"]))

    def test_placeholder_answer_is_not_accepted(self):
        task = TASKS["task_free_sufficient"]
        result = Runtime(SEED, PlaceholderBuyerModel(task)).run(task)
        self.assertEqual(result["answer"]["response_mode"], "runtime_sourced_fallback")
        self.assertIn("supplier_harbor", result["answer"]["answer"])
        self.assertIn("200/minute", result["answer"]["answer"])

    def test_premature_buyer_finish_recovers_with_checked_handoff(self):
        task = TASKS["task_free_sufficient"]
        result = Runtime(SEED, PrematureBuyerModel(task)).run(task)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["answer"]["response_mode"], "runtime_sourced_fallback")
        self.assertTrue(any(e["action"] == "research_recovery" for e in result["events"]))
        self.assertTrue(any(e["action"] == "handoff" and e["decision"] == "allow" for e in result["events"]))

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

    def test_model_tool_shorthand_is_still_checked(self):
        action = OllamaModel.normalize({"kind": "list_services", "args": {"item_ids": ["supplier_northstar"]}})
        self.assertEqual(action, Action("tool", {"name": "list_services", "item_ids": ["supplier_northstar"]}))
        self.assertEqual(OllamaModel.normalize({"kind": "purchase_service", "args": {"name": "list_services", "quote_id": "x"}}).args["name"], "purchase_service")
        runtime = Runtime(SEED, ReplayModel(TASKS["task_free_sufficient"]))
        runtime.actor = runtime.users["user_alice"]
        with self.assertRaisesRegex(Denied, "ROLE_TOOL_DENIED"):
            runtime.tool("researcher", OllamaModel.normalize({"kind": "purchase_service", "args": {"quote_id": "x"}}).args)

    def test_ollama_adapter_builds_state_specific_schema(self):
        response = {"message": {"content": json.dumps({"kind": "handoff", "args": {
            "objective": "Compare free catalog facts", "item_ids": ["supplier_northstar"]}})}}
        requests = []

        def fake_urlopen(request, timeout):
            requests.append((json.loads(request.data), timeout))
            return io.BytesIO(json.dumps(response).encode())

        with patch("agent_commerce_security.runtime.urlopen", fake_urlopen):
            action = OllamaModel("qwen3:1.7b").choose("buyer", {"request": "Compare", "item_ids": ["supplier_northstar"]}, [])
        self.assertEqual(action.kind, "handoff")
        self.assertEqual(requests[0][0]["format"]["properties"]["kind"]["enum"], ["handoff"])
        self.assertEqual(requests[0][1], 60)


if __name__ == "__main__":
    unittest.main()
