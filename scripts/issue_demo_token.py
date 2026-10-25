"""Print a short-lived local demo token for calling the loopback API."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.commerce import TokenAuthority
from agent_commerce_security.runtime import load_fixture
from run_step3 import make_store, signing_key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("user_id", nargs="?", default="user_alice")
    args = parser.parse_args()
    seed = load_fixture("seed.json")
    store = make_store()
    store.initialize(seed)
    with store.connect() as connection:
        user = connection.execute("SELECT * FROM demo_users WHERE user_id = ? AND active = 1", (args.user_id,)).fetchone()
    if user is None:
        parser.error("unknown or inactive demo user")
    token = TokenAuthority(signing_key()).issue(user["user_id"], user["tenant_id"], json.loads(user["scopes_json"]))
    print(token)


if __name__ == "__main__":
    main()
