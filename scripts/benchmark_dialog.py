"""Run reproducible, non-destructive dialog benchmark scenarios against /chat.

The script never confirms CREATE/DELETE operations, so benchmark runs do not
write or delete Google Calendar events. SEARCH scenarios are read-only.
Server-side component metrics are correlated through a benchmark session prefix.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from uuid import uuid4

import requests

DEFAULT_API_URL = os.getenv("ORGANIZER_API_URL", "http://127.0.0.1:8001").rstrip("/")
DEFAULT_USER_ID = os.getenv("LOCAL_USER_EXTERNAL_ID", "local-user")
DEFAULT_SCENARIOS = Path(__file__).resolve().parents[1] / "benchmarks" / "dialog_scenarios.json"
RUN_ID_RE = re.compile(r"^[0-9a-fA-F]{8}$")


def _is_subset(expected: dict, actual: dict) -> tuple[bool, str]:
    for key, expected_value in expected.items():
        if key not in actual:
            return False, f"missing event field {key!r}"
        if actual[key] != expected_value:
            return False, f"event.{key}: expected {expected_value!r}, got {actual[key]!r}"
    return True, ""


def _validate_turn(turn: dict, response: dict) -> list[str]:
    errors: list[str] = []
    expected_status = turn.get("expected_status")
    if expected_status and response.get("status") != expected_status:
        errors.append(
            f"status: expected {expected_status!r}, got {response.get('status')!r}"
        )

    expected_event = turn.get("expected_event")
    if expected_event:
        actual_event = response.get("event")
        if not isinstance(actual_event, dict):
            errors.append("expected event object, got none/non-object")
        else:
            matches, reason = _is_subset(expected_event, actual_event)
            if not matches:
                errors.append(reason)

    forbidden_fields = turn.get("forbidden_event_fields", [])
    actual_event = response.get("event")
    if isinstance(actual_event, dict):
        for field in forbidden_fields:
            if field in actual_event and actual_event[field] not in (None, ""):
                errors.append(f"event.{field} should be absent/empty, got {actual_event[field]!r}")

    return errors


def _resolve_run_id(run_id: str | None) -> str:
    if run_id is None:
        return uuid4().hex[:8]
    candidate = str(run_id).strip().lower()
    if not RUN_ID_RE.fullmatch(candidate):
        raise ValueError("run_id must contain exactly 8 hexadecimal characters")
    return candidate


def execute_benchmark(
    api_url: str,
    user_id: str,
    scenarios_path: Path,
    timeout: int,
    *,
    run_id: str | None = None,
    verbose: bool = True,
) -> dict:
    """Execute one benchmark run and return a machine-readable result."""
    scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    resolved_run_id = _resolve_run_id(run_id)
    session_prefix = f"bench-{resolved_run_id}-"
    failures = 0
    measured_turns = 0
    client_latencies: list[float] = []
    scenario_results: list[dict] = []

    def emit(message: str = "") -> None:
        if verbose:
            print(message)

    emit(f"Benchmark run: {resolved_run_id}")
    emit(f"API: {api_url}")
    emit(f"SQL session prefix: {session_prefix}%")
    emit()

    for scenario in scenarios:
        scenario_id = str(scenario["id"])
        session_id = (session_prefix + scenario_id)[:64]
        history: list[dict] = []
        draft_event = None
        scenario_errors: list[str] = []
        turn_results: list[dict] = []

        for turn_index, turn in enumerate(scenario["turns"], start=1):
            payload = {
                "message": turn["message"],
                "history": history,
                "draft_event": draft_event,
                "user_id": user_id,
                "session_id": session_id,
            }

            started = time.perf_counter()
            response = requests.post(
                f"{api_url}/chat",
                json=payload,
                timeout=timeout,
            )
            client_latency_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            data = response.json()

            measured_turns += 1
            client_latencies.append(client_latency_ms)
            turn_errors = _validate_turn(turn, data)
            scenario_errors.extend(
                f"turn {turn_index}: {error}" for error in turn_errors
            )
            turn_results.append(
                {
                    "turn": turn_index,
                    "status": data.get("status"),
                    "client_latency_ms": round(client_latency_ms, 3),
                    "errors": turn_errors,
                }
            )

            history.append({"role": "user", "content": turn["message"]})
            history.append({"role": "assistant", "content": data.get("message", "")})

            status = data.get("status")
            if status in {"confirmed", "cancelled", "deleted"}:
                draft_event = None
            elif isinstance(data.get("event"), dict):
                draft_event = data["event"]

            emit(
                f"  {scenario_id} turn {turn_index}: "
                f"status={status} client_ms={client_latency_ms:.0f}"
            )

        passed = not scenario_errors
        if not passed:
            failures += 1
            emit(f"FAIL {scenario_id}")
            for error in scenario_errors:
                emit(f"    - {error}")
        else:
            emit(f"PASS {scenario_id}")
        emit()

        scenario_results.append(
            {
                "id": scenario_id,
                "category": scenario.get("category"),
                "passed": passed,
                "turns": turn_results,
                "client_total_ms": round(
                    sum(item["client_latency_ms"] for item in turn_results), 3
                ),
            }
        )

    avg_client = sum(client_latencies) / len(client_latencies) if client_latencies else 0.0
    passed_scenarios = len(scenarios) - failures
    emit(
        f"Result: {passed_scenarios}/{len(scenarios)} scenarios passed; "
        f"{measured_turns} turns; avg client latency={avg_client:.0f} ms"
    )
    emit(f"Use SQL LIKE prefix: {session_prefix}%")

    return {
        "run_id": resolved_run_id,
        "session_prefix": session_prefix,
        "passed": failures == 0,
        "scenarios_total": len(scenarios),
        "scenarios_passed": passed_scenarios,
        "turns": measured_turns,
        "avg_client_latency_ms": round(avg_client, 3),
        "scenario_results": scenario_results,
    }


def run_benchmark(
    api_url: str,
    user_id: str,
    scenarios_path: Path,
    timeout: int,
    *,
    run_id: str | None = None,
    verbose: bool = True,
) -> int:
    result = execute_benchmark(
        api_url,
        user_id,
        scenarios_path,
        timeout,
        run_id=run_id,
        verbose=verbose,
    )
    return 0 if result["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OrganizerAI dialog benchmark")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--scenarios", type=Path, default=DEFAULT_SCENARIOS)
    parser.add_argument("--timeout", type=int, default=130)
    parser.add_argument("--run-id", help="Optional exact 8-character hexadecimal run id")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-scenario output")
    args = parser.parse_args()
    return run_benchmark(
        args.api_url.rstrip("/"),
        args.user_id,
        args.scenarios,
        args.timeout,
        run_id=args.run_id,
        verbose=not args.quiet,
    )


if __name__ == "__main__":
    raise SystemExit(main())
