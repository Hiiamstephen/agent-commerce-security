"""Deliver pending security decisions to the local deduplicated event store."""

import argparse
import json
import time

from run_step3 import make_store
from agent_commerce_security.audit import deliver_outbox


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--watch", action="store_true", help="Poll continuously and retry temporary failures")
    args = parser.parse_args()
    store = make_store()
    if not args.watch:
        print(json.dumps({"delivered": deliver_outbox(store, args.batch_size)}))
        return
    try:
        while True:
            try:
                count = deliver_outbox(store, args.batch_size)
                if count:
                    print(json.dumps({"delivered": count}), flush=True)
            except Exception as error:
                print(json.dumps({"delivery_error": type(error).__name__}), flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
