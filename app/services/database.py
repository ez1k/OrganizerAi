"""SQL Server persistence for OrganizerAI learning examples.

The chat API uses a stable external user identifier (currently ``local-user``
for local development). SQL Server stores users with a ``UNIQUEIDENTIFIER``
primary key, so this module owns the mapping between the external identifier
and the database UUID.
"""

import json
import os
from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


SQL_SERVER_CONNECTION = os.getenv(
    "SQL_SERVER_CONNECTION",
    "Data Source=DESKTOP-SN6B47K;Integrated Security=True;Persist Security Info=False;Pooling=False;MultipleActiveResultSets=False;Encrypt=True;TrustServerCertificate=True;Application Name=OrganizerAI;Command Timeout=0",
)
LOCAL_USER_EXTERNAL_ID = os.getenv("LOCAL_USER_EXTERNAL_ID", "local-user")
LOCAL_USER_DB_ID = os.getenv("LOCAL_USER_DB_ID", "00000000-0000-0000-0000-000000000001")


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create and cache the SQLAlchemy engine used by the application."""
    odbc = os.getenv("SQL_SERVER_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    connection = f"DRIVER={{{odbc}}};{SQL_SERVER_CONNECTION}"
    url = "mssql+pyodbc:///?odbc_connect=" + quote_plus(connection)
    return create_engine(url, pool_pre_ping=True, future=True)


def _normalize_external_user_id(external_user_id: str | None) -> str:
    """Return a non-empty external user id used by the API layer."""
    value = str(external_user_id or "").strip()
    return value or LOCAL_USER_EXTERNAL_ID


def _new_database_user_id(external_user_id: str) -> str:
    """Return the deterministic local UUID or a new UUID for future users."""
    if external_user_id == LOCAL_USER_EXTERNAL_ID:
        return str(UUID(LOCAL_USER_DB_ID))
    return str(uuid4())


def get_or_create_user_id(external_user_id: str | None) -> str:
    """Resolve an external user identifier to ``users.id``.

    For local development, ``local-user`` always receives the configured
    ``LOCAL_USER_DB_ID`` on first creation. If the row already exists, its
    existing UUID is respected. The lock keeps concurrent first requests from
    trying to create the same ``external_id`` twice.
    """
    external_id = _normalize_external_user_id(external_user_id)

    with get_engine().begin() as conn:
        existing_id = conn.execute(
            text("""
                SELECT id
                FROM dbo.users WITH (UPDLOCK, HOLDLOCK)
                WHERE external_id = :external_id
            """),
            {"external_id": external_id},
        ).scalar_one_or_none()

        if existing_id is not None:
            return str(existing_id)

        database_user_id = _new_database_user_id(external_id)
        conn.execute(
            text("""
                INSERT INTO dbo.users (id, external_id)
                VALUES (:id, :external_id)
            """),
            {"id": database_user_id, "external_id": external_id},
        )
        return database_user_id


def save_learning_example(
    user_id: str,
    message: str,
    result: dict[str, Any],
    corrected: bool = False,
) -> None:
    """Persist one interpreted chat example for the given external user id."""
    database_user_id = get_or_create_user_id(user_id)
    normalized_message = " ".join(str(message).lower().split())

    with get_engine().begin() as conn:
        conn.execute(
            text("""
                INSERT INTO dbo.learning_examples (
                    user_id,
                    message,
                    normalized_message,
                    result_json,
                    corrected
                )
                VALUES (
                    :user_id,
                    :message,
                    :normalized_message,
                    :result_json,
                    :corrected
                )
            """),
            {
                "user_id": database_user_id,
                "message": message,
                "normalized_message": normalized_message,
                "result_json": json.dumps(result, ensure_ascii=False),
                "corrected": corrected,
            },
        )


def find_learning_examples(
    user_id: str,
    message: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Find recent examples belonging to the same logical application user."""
    tokens = set(" ".join(str(message).lower().split()).split())
    if not tokens:
        return []

    database_user_id = get_or_create_user_id(user_id)
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT TOP 20 id, message, normalized_message, result_json, corrected
                FROM dbo.learning_examples
                WHERE user_id = :user_id
                ORDER BY corrected DESC, created_at DESC
            """),
            {"user_id": database_user_id},
        ).mappings().all()

    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        score = len(tokens & set(row["normalized_message"].split()))
        if not score:
            continue

        item = dict(row)
        item["result"] = json.loads(item.pop("result_json"))
        scored.append((score, item))

    scored.sort(
        key=lambda item: (bool(item[1].get("corrected")), item[0]),
        reverse=True,
    )
    return [item for _, item in scored[:limit]]


def format_learning_examples(examples: list[dict[str, Any]]) -> str:
    """Render stored structured examples as few-shot context for the LLM."""
    if not examples:
        return ""

    lines = ["\nPRZYKŁADY Z POPRZEDNICH INTERAKCJI:"]
    for example in examples:
        lines.append(f"UŻYTKOWNIK: {example['message']}")
        lines.append(f"JSON: {json.dumps(example['result'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"
