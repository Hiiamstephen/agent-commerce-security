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
    args = parser.parse_args()
    tasks = {t["task_id"]: t for t in load_fixture("tasks.json")["tasks"]}
    task = tasks[args.task_id]
    model = OllamaModel(args.ollama_model) if args.ollama_model else ReplayModel(task)
    print(json.dumps(Runtime(load_fixture("seed.json"), model).run(task), indent=2))


if __name__ == "__main__":
    main()
