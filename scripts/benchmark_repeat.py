"""Run the frozen dialog benchmark repeatedly and summarize client-side results.

Measured run ids share a five-hex batch prefix. Warm-up runs use unrelated ids,
so server-side SQL can select the measured batch exactly without mixing warm-up
latencies into the experiment.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from benchmark_dialog import (
    DEFAULT_API_URL,
    DEFAULT_SCENARIOS,
    DEFAULT_USER_ID,
    execute_benchmark,
)

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "benchmark_results"


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _scenario_summary(run_results: list[dict]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for run in run_results:
        for scenario in run.get("scenario_results", []):
            item = grouped.setdefault(
                scenario["id"],
                {
                    "scenario": scenario["id"],
                    "category": scenario.get("category"),
                    "passes": 0,
                    "client_total_ms": [],
                },
            )
            item["passes"] += int(bool(scenario.get("passed")))
            item["client_total_ms"].append(float(scenario.get("client_total_ms", 0.0)))

    summary: list[dict] = []
    for scenario_id in sorted(grouped):
        item = grouped[scenario_id]
        values = item["client_total_ms"]
        runs = len(values)
        summary.append(
            {
                "scenario": scenario_id,
                "category": item["category"],
                "runs": runs,
                "passes": item["passes"],
                "pass_rate_pct": round(100.0 * item["passes"] / runs, 2) if runs else 0.0,
                "avg_client_total_ms": round(statistics.fmean(values), 3) if values else 0.0,
                "median_client_total_ms": round(statistics.median(values), 3) if values else 0.0,
                "p95_client_total_ms": round(_percentile(values, 0.95), 3),
                "stddev_client_total_ms": round(statistics.stdev(values), 3) if len(values) > 1 else 0.0,
                "min_client_total_ms": round(min(values), 3) if values else 0.0,
                "max_client_total_ms": round(max(values), 3) if values else 0.0,
            }
        )
    return summary


def run_repeated_benchmark(
    *,
    runs: int,
    warmup_runs: int,
    api_url: str,
    user_id: str,
    scenarios_path: Path,
    timeout: int,
    pause_seconds: float,
    output_dir: Path,
    benchmark_version: str,
) -> dict:
    if runs <= 0:
        raise ValueError("runs must be greater than zero")
    if not 0 <= warmup_runs:
        raise ValueError("warmup_runs cannot be negative")
    if runs > 4095:
        raise ValueError("runs cannot exceed 4095 for the batch run-id format")

    batch_id = uuid4().hex[:5]
    started_at = datetime.now(timezone.utc)
    warmup_ids: list[str] = []
    measured_results: list[dict] = []
    run_errors: list[dict] = []

    print(f"Benchmark version: {benchmark_version}")
    print(f"Batch: {batch_id}")
    print(f"Measured runs: {runs}; warm-up runs: {warmup_runs}")
    print(f"API: {api_url}")
    print()

    for index in range(1, warmup_runs + 1):
        warmup_id = uuid4().hex[:8]
        warmup_ids.append(warmup_id)
        print(f"Warm-up {index}/{warmup_runs}: run={warmup_id}")
        execute_benchmark(
            api_url,
            user_id,
            scenarios_path,
            timeout,
            run_id=warmup_id,
            verbose=False,
        )
        if pause_seconds:
            time.sleep(pause_seconds)

    for index in range(1, runs + 1):
        run_id = f"{batch_id}{index:03x}"
        print(f"Measured {index}/{runs}: run={run_id}", end="")
        try:
            result = execute_benchmark(
                api_url,
                user_id,
                scenarios_path,
                timeout,
                run_id=run_id,
                verbose=False,
            )
            measured_results.append(result)
            print(
                f"  {'PASS' if result['passed'] else 'FAIL'} "
                f"{result['scenarios_passed']}/{result['scenarios_total']} "
                f"avg_client_ms={result['avg_client_latency_ms']:.0f}"
            )
        except Exception as exc:
            run_errors.append({"run_id": run_id, "error": f"{type(exc).__name__}: {exc}"})
            print(f"  ERROR {type(exc).__name__}: {exc}")

        if pause_seconds and index < runs:
            time.sleep(pause_seconds)

    completed_at = datetime.now(timezone.utc)
    fully_passed = sum(1 for result in measured_results if result.get("passed"))
    scenario_summary = _scenario_summary(measured_results)
    payload = {
        "benchmark_version": benchmark_version,
        "batch_id": batch_id,
        "sql_run_id_prefix": f"{batch_id}%",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": completed_at.isoformat(),
        "requested_runs": runs,
        "completed_runs": len(measured_results),
        "fully_passed_runs": fully_passed,
        "run_pass_rate_pct": round(100.0 * fully_passed / runs, 2),
        "warmup_runs": warmup_runs,
        "warmup_run_ids": warmup_ids,
        "run_errors": run_errors,
        "scenario_summary": scenario_summary,
        "runs": measured_results,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{benchmark_version}-{batch_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print(
        f"Measured result: {fully_passed}/{runs} full runs passed; "
        f"completed={len(measured_results)}; errors={len(run_errors)}"
    )
    print(f"SQL run-id prefix: {batch_id}%")
    print(f"JSON result: {output_path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Repeat OrganizerAI benchmark v1")
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--warmup-runs", type=int, default=1)
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--timeout", type=int, default=130)
    parser.add_argument("--pause-seconds", type=float, default=0.2)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--version", default="v1")
    args = parser.parse_args()

    result = run_repeated_benchmark(
        runs=args.runs,
        warmup_runs=args.warmup_runs,
        api_url=args.api_url.rstrip("/"),
        user_id=args.user_id,
        scenarios_path=args.scenarios,
        timeout=args.timeout,
        pause_seconds=max(0.0, args.pause_seconds),
        output_dir=args.output_dir,
        benchmark_version=args.version,
    )
    return 0 if result["fully_passed_runs"] == result["requested_runs"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
