"""Run the original scenarios plus new security regressions and optional Ollama tasks."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent_commerce_security.evaluation import run_deterministic, run_live


def markdown(report: dict) -> str:
    rows = report["results"]
    fixture = [row for row in rows if row["mode"].startswith("fixture")]
    live = [row for row in rows if row["mode"].startswith("ollama:")]
    fallbacks = sum(row.get("observed", {}).get("response_mode") == "runtime_sourced_fallback"
                    for row in live)
    paid_reports = sum(row.get("observed", {}).get("response_mode") == "runtime_paid_report"
                       for row in live)
    lines = ["# Step 5 measured evaluation", "", f"Generated: {report['created_at']}", "",
             f"Fixture cases: {sum(row['security_pass'] and row['quality_pass'] for row in fixture)}/{len(fixture)} passed.  "
             f"Live runs: {len(live)}; transaction and role invariants "
             f"{sum(row['security_pass'] for row in live)}/{len(live)}; "
             f"end-to-end task fidelity {sum(row['quality_pass'] for row in live)}/{len(live)}; "
             f"runtime free-answer fallbacks {fallbacks}/{len(live)}; "
             f"runtime paid-report answers {paid_reports}/{len(live)}.", "",
             f"Security controls and task fidelity are scored separately. Each case gets fresh {report.get('backend', 'sqlite')} state. "
             "The live invariant gate is narrower than the deterministic attack suite.", "",
             "| Case | Mode | Control gate | Task fidelity | Charges | Final events | Time (ms) | Observed |",
             "| --- | --- | --- | --- | ---: | ---: | ---: | --- |"]
    for row in rows:
        counts = row.get("counts", {})
        observed = row.get("observed", {})
        detail = (row.get("error") or observed.get("reason_code") or observed.get("answer_status")
                  or observed.get("response_mode") or observed.get("status") or "checked")
        lines.append(f"| `{row['case_id']}` | `{row['mode']}` | {'pass' if row['security_pass'] else 'FAIL'} "
                     f"| {'pass' if row['quality_pass'] else 'FAIL'} | {counts.get('charges', '—')} "
                     f"| {counts.get('final_events', '—')} | {row['latency_ms']} | {str(detail).replace('|', '/')} |")
    failures = [row for row in rows if not row["security_pass"] or not row["quality_pass"]]
    lines += ["", "## Failures and observations", ""]
    if not failures:
        lines.append("No failures in this measured run.")
    for row in failures:
        failed_checks = [name for group in ("security_checks", "quality_checks")
                         for name, passed in row.get(group, {}).items() if not passed]
        observed = {key: value for key, value in row.get("observed", {}).items() if key != "events"}
        if "events" in row.get("observed", {}):
            observed["event_count"] = len(row["observed"]["events"])
        lines.append(f"- `{row['case_id']}`: {', '.join(failed_checks) or row.get('error', 'unknown failure')}; "
                     f"observed `{json.dumps(observed, sort_keys=True)}`.")
    lines += ["", "## Limits", "",
              "Fixture replay checks policy and transaction behavior; it does not measure model reliability. "
              "Live control scores check transaction, event, and role invariants, not every attack boundary. "
              "The paid model path is constrained by a trusted task requirement and state-specific action schemas. "
              "Paid-report answers and free-answer fallbacks are assembled by the runtime from validated data. "
              "Ollama runs are local and may vary across repetitions. SQLite uses a separate temporary database "
              "per case; PostgreSQL uses a dedicated evaluation database cleared between cases. "
              "A worker process crash is checked separately in the PostgreSQL tests. "
              "No real payment or external event sink is involved.", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("fixture", "live", "all"), default="fixture")
    parser.add_argument("--ollama-model", default="qwen3:1.7b")
    parser.add_argument("--repetitions", type=int, default=2)
    parser.add_argument("--postgres-dsn", help="Use and reset only database agent_commerce_security_eval")
    parser.add_argument("--json-out", type=Path, default=ROOT / "artifacts" / "step5-results.json")
    parser.add_argument("--markdown-out", type=Path, default=ROOT / "docs" / "step5-results.md")
    args = parser.parse_args()
    if not 1 <= args.repetitions <= 10:
        parser.error("--repetitions must be between 1 and 10")
    results = []
    if args.mode in ("fixture", "all"):
        results.extend(run_deterministic(args.postgres_dsn))
    if args.mode in ("live", "all"):
        results.extend(run_live(args.ollama_model, args.repetitions, args.postgres_dsn))
    report = {"created_at": datetime.now(timezone.utc).isoformat(), "model": args.ollama_model,
              "backend": "postgres" if args.postgres_dsn else "sqlite",
              "repetitions": args.repetitions, "results": results}
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    args.markdown_out.write_text(markdown(report), encoding="utf-8")
    print(json.dumps({"cases": len(results), "security_passes": sum(row["security_pass"] for row in results),
                      "quality_passes": sum(row["quality_pass"] for row in results),
                      "json": str(args.json_out), "markdown": str(args.markdown_out)}))
    if any(not row["security_pass"] or (row["mode"].startswith("fixture") and not row["quality_pass"])
           for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
