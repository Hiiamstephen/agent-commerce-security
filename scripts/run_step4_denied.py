"""Record a deliberately over-scoped buyer-to-researcher handoff."""

import json

from run_step3 import make_store, signing_key
from agent_commerce_security.commerce import CommerceService, TokenAuthority
from agent_commerce_security.runtime import Action, Runtime, load_fixture


class OverScopedHandoff:
    def choose(self, role, view, observations):
        return Action("handoff", {"objective": "Read an item outside this task",
                                  "item_ids": ["supplier_not_in_task"]})


def main() -> None:
    seed = load_fixture("seed.json")
    task = next(item for item in load_fixture("tasks.json")["tasks"]
                if item["task_id"] == "task_free_sufficient")
    store = make_store()
    store.initialize(seed)
    authority = TokenAuthority(signing_key())
    actor = next(item for item in seed["users"] if item["user_id"] == task["actor_user_id"])
    token = authority.issue(actor["user_id"], actor["tenant_id"], actor["scopes"])
    result = Runtime(seed, OverScopedHandoff(), commerce=CommerceService(store, authority, seed["policy"]),
                     bearer_token=token).run(task)
    print(json.dumps({key: result[key] for key in ("status", "reason_code", "run_id")}, indent=2))


if __name__ == "__main__":
    main()
