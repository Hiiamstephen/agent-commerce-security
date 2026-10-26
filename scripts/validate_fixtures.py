"""Validate the synthetic Step 1 fixtures without third-party dependencies."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))


def unique_index(rows: list[dict], key: str) -> dict[str, dict]:
    indexed = {row[key]: row for row in rows}
    assert len(indexed) == len(rows), f"Duplicate {key}"
    return indexed


def integer_minor(value: object, name: str, *, positive: bool = False) -> None:
    assert type(value) is int, f"{name} must be an integer number of cents"
    assert value > 0 if positive else value >= 0, f"{name} must be nonnegative"


def main() -> None:
    seed = load("seed.json")
    task_file = load("tasks.json")
    assert seed["schema_version"] == task_file["schema_version"] == 1
    assert seed["currency"] == "USD"
    assert "invented" in seed["fictional_notice"].lower()

    tenants = unique_index(seed["tenants"], "tenant_id")
    users = unique_index(seed["users"], "user_id")
    agents = unique_index(seed["agent_roles"], "agent_id")
    budgets = unique_index(seed["budgets"], "budget_id")
    sellers = unique_index(seed["sellers"], "seller_id")
    items = unique_index(seed["catalog_items"], "item_id")
    services = unique_index(seed["services"], "service_id")
    reports = unique_index(seed["paid_reports"], "report_id")
    tasks = unique_index(task_file["tasks"], "task_id")

    assert set(agents) == {"buyer", "researcher"}
    assert set(agents["researcher"]["allowed_tools"]) == {"list_services"}
    assert set(agents["buyer"]["allowed_tools"]) == {
        "list_services", "get_quote", "purchase_service"
    }
    assert agents["buyer"]["can_delegate_to"] == ["researcher"]
    assert agents["researcher"]["can_delegate_to"] == []

    for user in users.values():
        assert user["tenant_id"] in tenants
        assert user["active"] is True
        assert len(user["scopes"]) == len(set(user["scopes"]))
    for budget in budgets.values():
        owner = users[budget["user_id"]]
        assert budget["tenant_id"] == owner["tenant_id"]
        assert budget["currency"] == seed["currency"]
        integer_minor(budget["limit_minor"], "budget limit")
        integer_minor(budget["remaining_minor"], "remaining budget")
        assert budget["remaining_minor"] <= budget["limit_minor"]
    for item in items.values():
        assert item["source_id"]
        assert item["free_facts"]
    for service in services.values():
        assert service["seller_id"] in sellers
        assert service["report_id"] in reports
        assert service["currency"] == seed["currency"]
        integer_minor(service["price_minor"], "service price", positive=True)
    for report in reports.values():
        assert report["service_id"] in services
        assert report["source_id"]
        assert set(report["sample_error_rate_percent"]) == set(items)
        assert all(type(rate) in (int, float) and 0 <= rate <= 100
                   for rate in report["sample_error_rate_percent"].values())

    policy = seed["policy"]
    assert policy["version"]
    assert set(policy["approved_seller_ids"]) <= set(sellers)
    assert all(sellers[seller_id]["approved"] for seller_id in policy["approved_seller_ids"])
    integer_minor(policy["max_single_purchase_minor"], "max purchase", positive=True)
    assert policy["quote_ttl_seconds"] > 0
    assert policy["max_model_steps_per_run"] > 0
    assert policy["max_handoff_hops"] == 1

    for task in tasks.values():
        assert task["actor_user_id"] in users
        assert set(task["catalog_item_ids"]) <= set(items)
        expected = task["expected"]
        assert expected["handoff"] in {"allow", "deny"}
        assert expected["purchase_decision"] in {"allow", "deny", "not_requested"}
        assert expected["purchase_count"] in {0, 1}
        if expected["purchase_count"] == 1:
            assert expected["purchase_decision"] == "allow"
            assert expected["report_id"] in reports
        else:
            assert expected["report_id"] is None
        if "requested_tenant_id" in task:
            assert task["requested_tenant_id"] in tenants
            assert task["requested_tenant_id"] != users[task["actor_user_id"]]["tenant_id"]
            assert expected["handoff"] == "deny"
            assert expected["purchase_count"] == 0

    for task_id, requirement in seed.get("task_requirements", {}).items():
        assert task_id in tasks
        allowed = requirement["allowed_purchase_service_ids"]
        assert isinstance(allowed, list) and len(allowed) == len(set(allowed))
        assert all(service_id in services for service_id in allowed)
        service_id = requirement.get("required_report_service_id")
        if service_id is not None:
            assert service_id in allowed
            assert services[service_id]["report_id"] == tasks[task_id]["expected"]["report_id"]
        if tasks[task_id]["expected"]["purchase_count"] == 0:
            assert not allowed

    assert tasks["task_paid_needed"]["expected"]["purchase_count"] == 1
    assert tasks["task_free_sufficient"]["expected"]["purchase_count"] == 0
    assert services["service_reliability_report"]["price_minor"] <= budgets["budget_alice_usd"]["remaining_minor"]
    assert services["service_reliability_report"]["price_minor"] <= policy["max_single_purchase_minor"]
    print(
        f"Fixtures valid: {len(tenants)} tenants, {len(users)} users, "
        f"{len(items)} suppliers, {len(services)} paid service, {len(tasks)} tasks."
    )


if __name__ == "__main__":
    main()
