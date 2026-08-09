import json
import os
from pathlib import Path
from typing import Any

STORE_PATH = Path(os.getenv("LEARNING_STORE_PATH", "data/learning_examples.jsonl"))


def _normalize(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def record_example(message: str, result: dict[str, Any], *, corrected: bool = False) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {"message": message.strip(), "normalized": _normalize(message), "result": result, "corrected": corrected}
    with STORE_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def find_similar_examples(message: str, limit: int = 3) -> list[dict[str, Any]]:
    if not STORE_PATH.exists():
        return []
    tokens = set(_normalize(message).split())
    scored = []
    with STORE_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            score = len(tokens & set(item.get("normalized", "").split()))
            if score:
                scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored[:limit]]


def format_examples(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return ""
    lines = ["\nDOBRE PRZYKŁADY Z POPRZEDNICH INTERAKCJI:"]
    for example in examples:
        lines.append(f"UŻYTKOWNIK: {example['message']}")
        lines.append(f"POPRAWNY JSON: {json.dumps(example['result'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"
