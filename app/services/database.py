import json
import os
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from urllib.parse import quote_plus


SQL_SERVER_CONNECTION = os.getenv(
    "SQL_SERVER_CONNECTION",
    "Data Source=DESKTOP-SN6B47K;Integrated Security=True;Persist Security Info=False;Pooling=False;MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=True;Application Name=OrganizerAI;Command Timeout=0",
)


def get_engine() -> Engine:
    odbc = os.getenv("SQL_SERVER_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    connection = f"DRIVER={{{odbc}}};{SQL_SERVER_CONNECTION}"
    url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(connection)
    return create_engine(url, pool_pre_ping=True, future=True)


def save_learning_example(user_id: str, message: str, result: dict[str, Any], corrected: bool = False) -> None:
    with get_engine().begin() as conn:
        conn.execute(text("""
            INSERT INTO learning_examples (user_id, message, normalized_message, result_json, corrected)
            VALUES (:user_id, :message, :normalized_message, :result_json, :corrected)
        """), {
            "user_id": user_id,
            "message": message,
            "normalized_message": " ".join(message.lower().split()),
            "result_json": json.dumps(result, ensure_ascii=False),
            "corrected": corrected,
        })


def find_learning_examples(user_id: str, message: str, limit: int = 3) -> list[dict[str, Any]]:
    tokens = set(" ".join(message.lower().split()).split())
    if not tokens:
        return []
    with get_engine().connect() as conn:
        rows = conn.execute(text("""
            SELECT TOP 20 id, message, normalized_message, result_json, corrected
            FROM learning_examples
            WHERE user_id = :user_id
            ORDER BY created_at DESC
        """), {"user_id": user_id}).mappings().all()

    scored = []
    for row in rows:
        score = len(tokens & set(row["normalized_message"].split()))
        if score:
            item = dict(row)
            item["result"] = json.loads(item.pop("result_json"))
            scored.append((score, item))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:limit]]


def format_learning_examples(examples: list[dict[str, Any]]) -> str:
    if not examples:
        return ""
    lines = ["\nDOBRE PRZYKŁADY Z POPRZEDNICH INTERAKCJI:"]
    for example in examples:
        lines.append(f"UŻYTKOWNIK: {example['message']}")
        lines.append(f"POPRAWNY JSON: {json.dumps(example['result'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"
