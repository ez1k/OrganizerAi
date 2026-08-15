"""Evaluate OrganizerAI semantic NLU and optional deterministic dialog policy.

Raw mode measures Mistral semantic extraction. Deterministic mode applies the
same policy used by runtime after the model, without executing Calendar calls.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.dialog_policy import apply_dialog_policy
from app.services.llm_service import ask_llm_semantic

DEFAULT_DATASET = PROJECT_ROOT / "benchmarks" / "nlp_quality_v1.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "benchmark_results"
POLISH_TRANSLATION = str.maketrans({"ł": "l"})


def _normalize(value) -> str:
    text = " ".join(str(value or "").strip().casefold().split())
    text = text.translate(POLISH_TRANSLATION)
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def _normalize_time(value) -> str:
    text = _normalize(value).replace(".", ":")
    if text.startswith("o "):
        text = text[2:].strip()
    parts = text.split(":")
    if len(parts) == 1 and parts[0].isdigit():
        return f"{int(parts[0]):02d}:00"
    if len(parts) == 2 and all(part.isdigit() for part in parts):
        return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
    return text


def _equal(field: str, expected, actual) -> bool:
    if field == "duration_minutes":
        try:
            return int(actual) == int(expected)
        except (TypeError, ValueError):
            return False
    if field == "time_hint":
        return _normalize_time(actual) == _normalize_time(expected)
    return _normalize(actual) == _normalize(expected)


def _validate_object(
    label: str,
    expected: dict | None,
    actual,
) -> tuple[list[str], int, int, int, int]:
    if not expected:
        return [], 0, 0, 0, 0

    errors: list[str] = []
    slot_total = 0
    slot_correct = 0
    hallucination_total = 0
    hallucination_correct = 0

    if not isinstance(actual, dict):
        checks = len(expected.get("equals", {})) + len(expected.get("contains", {}))
        missing_checks = len(expected.get("missing", []))
        return (
            [f"{label}: expected object, got {type(actual).__name__}"],
            checks,
            0,
            missing_checks,
            0,
        )

    for field, expected_value in expected.get("equals", {}).items():
        slot_total += 1
        actual_value = actual.get(field)
        if _equal(field, expected_value, actual_value):
            slot_correct += 1
        else:
            errors.append(
                f"{label}.{field}: expected {expected_value!r}, got {actual_value!r}"
            )

    for field, needles in expected.get("contains", {}).items():
        slot_total += 1
        actual_value = _normalize(actual.get(field))
        normalized_needles = [_normalize(value) for value in needles]
        if actual_value and any(needle in actual_value for needle in normalized_needles):
            slot_correct += 1
        else:
            errors.append(
                f"{label}.{field}: expected semantic fragment {needles!r}, got {actual.get(field)!r}"
            )

    for field in expected.get("missing", []):
        hallucination_total += 1
        if field not in actual or actual.get(field) in (None, ""):
            hallucination_correct += 1
        else:
            errors.append(
                f"{label}.{field}: should be missing/empty, got {actual.get(field)!r}"
            )

    return errors, slot_total, slot_correct, hallucination_total, hallucination_correct


def _find_forbidden_key(value, forbidden: set[str], path: str = "result") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in forbidden and child not in (None, ""):
                found.append(child_path)
            found.extend(_find_forbidden_key(child, forbidden, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_find_forbidden_key(child, forbidden, f"{path}[{index}]"))
    return found


def _expected_counts(case: dict) -> dict[str, int]:
    expected = case.get("expected", {})
    slot_total = 0
    hallucination_total = 0
    for object_name in ("event", "search"):
        spec = expected.get(object_name) or {}
        slot_total += len(spec.get("equals", {})) + len(spec.get("contains", {}))
        hallucination_total += len(spec.get("missing", []))
    hallucination_total += int(bool(case.get("forbidden_keys_anywhere")))
    return {
        "intent_total": int(expected.get("operation") is not None),
        "status_total": int(expected.get("status") is not None),
        "slot_total": slot_total,
        "hallucination_total": hallucination_total,
    }


def _validate_case(case: dict, result: dict) -> dict:
    expected = case.get("expected", {})
    errors: list[str] = []

    expected_operation = expected.get("operation")
    intent_total = int(expected_operation is not None)
    intent_correct = 0
    if expected_operation is not None:
        if _normalize(result.get("operation")) == _normalize(expected_operation):
            intent_correct = 1
        else:
            errors.append(
                f"operation: expected {expected_operation!r}, got {result.get('operation')!r}"
            )

    expected_status = expected.get("status")
    status_total = int(expected_status is not None)
    status_correct = 0
    if expected_status is not None:
        if _normalize(result.get("status")) == _normalize(expected_status):
            status_correct = 1
        else:
            errors.append(
                f"status: expected {expected_status!r}, got {result.get('status')!r}"
            )

    event_errors, event_total, event_correct, event_h_total, event_h_correct = _validate_object(
        "event", expected.get("event"), result.get("event")
    )
    search_errors, search_total, search_correct, search_h_total, search_h_correct = _validate_object(
        "search", expected.get("search"), result.get("search")
    )
    errors.extend(event_errors)
    errors.extend(search_errors)

    forbidden_keys = set(case.get("forbidden_keys_anywhere", []))
    forbidden_total = int(bool(forbidden_keys))
    forbidden_correct = 0
    if forbidden_keys:
        found = _find_forbidden_key(result, forbidden_keys)
        if found:
            errors.append(f"forbidden keys populated: {', '.join(found)}")
        else:
            forbidden_correct = 1

    return {
        "passed": not errors,
        "errors": errors,
        "intent_total": intent_total,
        "intent_correct": intent_correct,
        "status_total": status_total,
        "status_correct": status_correct,
        "slot_total": event_total + search_total,
        "slot_correct": event_correct + search_correct,
        "hallucination_total": event_h_total + search_h_total + forbidden_total,
        "hallucination_correct": event_h_correct + search_h_correct + forbidden_correct,
    }


def _pct(correct: int, total: int) -> float:
    return round(100.0 * correct / total, 2) if total else 100.0


def _empty_failed_validation(case: dict, error: str) -> dict:
    counts = _expected_counts(case)
    return {
        "passed": False,
        "errors": [error],
        "intent_total": counts["intent_total"],
        "intent_correct": 0,
        "status_total": counts["status_total"],
        "status_correct": 0,
        "slot_total": counts["slot_total"],
        "slot_correct": 0,
        "hallucination_total": counts["hallucination_total"],
        "hallucination_correct": 0,
    }


def _accumulate(target, validation: dict) -> None:
    target["evaluations"] += 1
    target["passed"] += int(validation["passed"])
    for metric in (
        "intent_total",
        "intent_correct",
        "status_total",
        "status_correct",
        "slot_total",
        "slot_correct",
        "hallucination_total",
        "hallucination_correct",
    ):
        target[metric] += validation[metric]


def run_nlp_benchmark(
    *,
    dataset_path: Path,
    user_id: str,
    runs: int,
    output_dir: Path,
    version: str,
    policy_mode: str = "raw",
) -> dict:
    if runs <= 0:
        raise ValueError("runs must be greater than zero")
    if policy_mode not in {"raw", "deterministic"}:
        raise ValueError("policy_mode must be 'raw' or 'deterministic'")

    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    batch_id = uuid4().hex[:8]
    started_at = datetime.now(timezone.utc)
    case_results: list[dict] = []
    latencies: list[float] = []

    totals = defaultdict(int)
    raw_totals = defaultdict(int)
    category_totals: dict[str, defaultdict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    print(f"NLP benchmark: {version}")
    print(f"Dataset: {dataset_path}")
    print(f"Policy mode: {policy_mode}")
    print(f"Cases: {len(cases)}; runs: {runs}; total evaluations: {len(cases) * runs}")
    print(f"User/retrieval context: {user_id}")
    print(f"Batch: {batch_id}")
    print()

    for run_index in range(1, runs + 1):
        print(f"Run {run_index}/{runs}")
        for case in cases:
            started = time.perf_counter()
            try:
                raw_result = ask_llm_semantic(
                    message=case["message"],
                    history=case.get("history", []),
                    draft_event=case.get("draft_event"),
                    user_id=user_id,
                )
                latency_ms = (time.perf_counter() - started) * 1000
                raw_validation = _validate_case(case, raw_result)
                result = (
                    apply_dialog_policy(
                        case["message"],
                        raw_result,
                        current_state=case.get("draft_event"),
                    )
                    if policy_mode == "deterministic"
                    else raw_result
                )
                validation = _validate_case(case, result)
                exception = None
            except Exception as exc:
                latency_ms = (time.perf_counter() - started) * 1000
                raw_result = None
                result = None
                exception = f"{type(exc).__name__}: {exc}"
                raw_validation = _empty_failed_validation(case, exception)
                validation = _empty_failed_validation(case, exception)

            latencies.append(latency_ms)
            category = str(case.get("category") or "other")
            _accumulate(totals, validation)
            _accumulate(raw_totals, raw_validation)
            _accumulate(category_totals[category], validation)

            state = "PASS" if validation["passed"] else "FAIL"
            print(f"  {state} {case['id']}  {latency_ms:.0f} ms")
            if not validation["passed"]:
                for error in validation["errors"]:
                    print(f"      - {error}")

            case_results.append(
                {
                    "run": run_index,
                    "id": case["id"],
                    "category": category,
                    "message": case["message"],
                    "latency_ms": round(latency_ms, 3),
                    "passed": validation["passed"],
                    "errors": validation["errors"],
                    "validation": {
                        key: value
                        for key, value in validation.items()
                        if key not in {"passed", "errors"}
                    },
                    "raw_validation": {
                        key: value
                        for key, value in raw_validation.items()
                        if key not in {"passed", "errors"}
                    },
                    "raw_result": raw_result,
                    "result": result,
                    "exception": exception,
                }
            )
        print()

    category_summary = []
    for category in sorted(category_totals):
        item = category_totals[category]
        category_summary.append(
            {
                "category": category,
                "evaluations": item["evaluations"],
                "case_pass_rate_pct": _pct(item["passed"], item["evaluations"]),
                "intent_accuracy_pct": _pct(item["intent_correct"], item["intent_total"]),
                "status_accuracy_pct": _pct(item["status_correct"], item["status_total"]),
                "slot_accuracy_pct": _pct(item["slot_correct"], item["slot_total"]),
                "hallucination_free_pct": _pct(
                    item["hallucination_correct"], item["hallucination_total"]
                ),
            }
        )

    summary = {
        "evaluations": totals["evaluations"],
        "passed": totals["passed"],
        "case_pass_rate_pct": _pct(totals["passed"], totals["evaluations"]),
        "intent_accuracy_pct": _pct(totals["intent_correct"], totals["intent_total"]),
        "status_accuracy_pct": _pct(totals["status_correct"], totals["status_total"]),
        "slot_accuracy_pct": _pct(totals["slot_correct"], totals["slot_total"]),
        "hallucination_free_pct": _pct(
            totals["hallucination_correct"], totals["hallucination_total"]
        ),
        "avg_latency_ms": round(statistics.fmean(latencies), 2) if latencies else 0.0,
        "median_latency_ms": round(statistics.median(latencies), 2) if latencies else 0.0,
    }
    raw_summary = {
        "intent_accuracy_pct": _pct(raw_totals["intent_correct"], raw_totals["intent_total"]),
        "slot_accuracy_pct": _pct(raw_totals["slot_correct"], raw_totals["slot_total"]),
        "hallucination_free_pct": _pct(
            raw_totals["hallucination_correct"], raw_totals["hallucination_total"]
        ),
    }

    payload = {
        "benchmark_version": version,
        "batch_id": batch_id,
        "dataset": str(dataset_path),
        "user_id": user_id,
        "runs": runs,
        "policy_mode": policy_mode,
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "raw_semantic_summary": raw_summary,
        "category_summary": category_summary,
        "case_results": case_results,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"nlp-{version}-{batch_id}.json"
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Summary")
    print(f"  case pass rate:      {summary['case_pass_rate_pct']:.2f}%")
    print(f"  intent accuracy:     {summary['intent_accuracy_pct']:.2f}%")
    print(f"  status accuracy:     {summary['status_accuracy_pct']:.2f}%")
    print(f"  slot accuracy:       {summary['slot_accuracy_pct']:.2f}%")
    print(f"  hallucination-free:  {summary['hallucination_free_pct']:.2f}%")
    if policy_mode == "deterministic":
        print("Raw semantic NLU")
        print(f"  raw intent accuracy:    {raw_summary['intent_accuracy_pct']:.2f}%")
        print(f"  raw slot accuracy:      {raw_summary['slot_accuracy_pct']:.2f}%")
        print(f"  raw hallucination-free: {raw_summary['hallucination_free_pct']:.2f}%")
    print(f"  avg LLM latency:     {summary['avg_latency_ms']:.0f} ms")
    print(f"  median LLM latency:  {summary['median_latency_ms']:.0f} ms")
    print(f"JSON result: {output_path}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate OrganizerAI NLP quality")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--version", default="v1")
    parser.add_argument(
        "--policy",
        choices=("raw", "deterministic"),
        default="raw",
        help="Evaluate raw semantic NLU or semantic NLU after deterministic dialog policy.",
    )
    parser.add_argument(
        "--min-pass-rate",
        type=float,
        default=None,
        help="Optional quality gate. Without it, measured NLP failures do not fail the process.",
    )
    args = parser.parse_args()

    result = run_nlp_benchmark(
        dataset_path=args.dataset,
        user_id=args.user_id,
        runs=args.runs,
        output_dir=args.output_dir,
        version=args.version,
        policy_mode=args.policy,
    )
    if args.min_pass_rate is None:
        return 0
    return 0 if result["summary"]["case_pass_rate_pct"] >= args.min_pass_rate else 1


if __name__ == "__main__":
    raise SystemExit(main())
