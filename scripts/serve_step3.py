"""Serve the local demo API on loopback."""

from pathlib import Path
import sys
from wsgiref.simple_server import make_server

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.api import DemoAPI
from agent_commerce_security.commerce import CommerceService, TokenAuthority
from agent_commerce_security.runtime import load_fixture
from run_step3 import make_store, signing_key


def main() -> None:
    seed = load_fixture("seed.json")
    store = make_store()
    store.initialize(seed)
    service = CommerceService(store, TokenAuthority(signing_key()), seed["policy"])
    app = DemoAPI(service, seed["catalog_items"])
    with make_server("127.0.0.1", 8008, app) as server:
        print("Demo API listening at http://127.0.0.1:8008", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
