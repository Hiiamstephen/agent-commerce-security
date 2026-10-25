"""Run a local signed-token demo with persistent mock budget and purchases."""

import argparse
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.commerce import CommerceService, PostgresStore, Store, TokenAuthority
from agent_commerce_security.runtime import OllamaModel, ReplayModel, Runtime, load_fixture

DATA_DIR = ROOT / "local-data"
DB_PATH = DATA_DIR / "demo.sqlite3"
KEY_PATH = DATA_DIR / "signing.key"


def make_store() -> Store | PostgresStore:
    if os.environ.get("ACS_STORE") == "sqlite":
        return Store(DB_PATH)
    if os.environ.get("ACS_STORE") not in (None, "postgres"):
        raise ValueError("ACS_STORE must be postgres or sqlite")
    return PostgresStore(os.environ.get("ACS_POSTGRES_DSN", "dbname=agent_commerce_security_demo"))


def signing_key() -> bytes:
    DATA_DIR.mkdir(exist_ok=True)
    try:
        descriptor = os.open(KEY_PATH, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as file:
            file.write(secrets.token_bytes(32))
    key = KEY_PATH.read_bytes()
    if len(key) != 32 or KEY_PATH.stat().st_mode & 0o077:
        raise RuntimeError("Local signing key must be 32 bytes and owner-readable only")
    return key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", nargs="?", default="task_paid_needed")
    parser.add_argument("--reset", action="store_true", help="Reset only the ignored local demo database")
    parser.add_argument("--ollama-model", help="Use a local Ollama model instead of fixture replay")
    parser.add_argument("--trace", action="store_true", help="Include runtime decision events")
    args = parser.parse_args()

    seed = load_fixture("seed.json")
    tasks = {task["task_id"]: task for task in load_fixture("tasks.json")["tasks"]}
    task = tasks[args.task_id]
    if args.reset and os.environ.get("ACS_STORE") != "sqlite":
        parser.error("--reset is available only for the local SQLite database")
    if args.reset:
        DB_PATH.unlink(missing_ok=True)
    store = make_store()
    store.initialize(seed)
    authority = TokenAuthority(signing_key())
    user = next(user for user in seed["users"] if user["user_id"] == task["actor_user_id"])
    token = authority.issue(user["user_id"], user["tenant_id"], user["scopes"])
    service = CommerceService(store, authority, seed["policy"])
    model = OllamaModel(args.ollama_model) if args.ollama_model else ReplayModel(task)
    result = Runtime(seed, model, max_seconds=180 if args.ollama_model else 30,
                     commerce=service, bearer_token=token).run(task)
    if not args.trace:
        result = {key: result[key] for key in ("status", "reason_code", "answer", "steps") if key in result}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
