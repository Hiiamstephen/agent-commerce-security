"""Run a Step 2 task with deterministic replay or a local Ollama model."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_commerce_security.runtime import OllamaModel, ReplayModel, Runtime, load_fixture


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id", nargs="?", default="task_free_sufficient")
    parser.add_argument("--ollama-model", help="Use a model served by local Ollama instead of fixture replay")
    parser.add_argument("--compact", action="store_true", help="Show the outcome without the full trace")
    args = parser.parse_args()
    tasks = {t["task_id"]: t for t in load_fixture("tasks.json")["tasks"]}
    task = tasks[args.task_id]
    model = OllamaModel(args.ollama_model) if args.ollama_model else ReplayModel(task)
    result = Runtime(load_fixture("seed.json"), model, max_seconds=180 if args.ollama_model else 30).run(task)
    if args.compact:
        result = {key: result[key] for key in ("status", "answer", "reason_code", "steps") if key in result}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
