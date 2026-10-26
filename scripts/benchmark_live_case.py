"""One isolated model trial; the parent benchmark enforces a wall-clock timeout."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.evaluation import ATTACKS, run_attack_corpus


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--attack-id", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--postgres-dsn")
    args = parser.parse_args()
    if args.attack_id not in {item["id"] for item in ATTACKS}:
        parser.error("unknown attack ID")
    rows = run_attack_corpus(args.model, 1, args.postgres_dsn, attack_ids={args.attack_id})
    if len(rows) != 1:
        raise RuntimeError("exactly one attack result required")
    print(json.dumps(rows[0]), flush=True)


if __name__ == "__main__":
    main()
