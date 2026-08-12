"""SQL Server persistence for OrganizerAI learning examples and feedback.

The chat API uses a stable external user identifier (currently ``local-user``
for local development). SQL Server stores users with a ``UNIQUEIDENTIFIER``
primary key, so this module owns the mapping between the external identifier
and the database UUID.

Raw backend interpretations may still be stored in ``learning_examples`` with
``corrected = 0`` for diagnostics. Only explicitly verified examples are read
back as few-shot context for the LLM. New raw and verified rows are deduplicated
semantically, while existing historical raw rows remain untouched for audit.
"""

import json
import os
from functools import lru_cache
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine


DEFAULT_SQL_SERVER_CONNECTION = (
    "Server=DESKTOP-SN6B47K;"
    "Database=ai_organizer;"
    "Trusted_Connection=Yes;"
    "Encrypt=Yes;"
    "TrustServerCertificate=Yes;"
    "APP=OrganizerAI"
)
SQL_SERVER_CONNECTION = os.getenv(
    "SQL_SERVER_CONNECTION",
    DEFAULT_SQL_SERVER_CONNECTION,
)
LOCAL_USER_EXTERNAL_ID = os.getenv("LOCAL_USER_EXTERNAL_ID", "local-user")
LOCAL_USER_DB_ID = os.getenv("LOCAL_USER_DB_ID", "00000000-0000-0000-0000-000000000001")


def _odbc_boolean(value: str) -> str | None:
    """Convert common boolean spellings to ODBC ``Yes``/``No`` values."""
    normalized = str(value).strip().casefold()
    if normalized in {"true", "1", "yes", "y", "on", "sspi"}:
        return "Yes"
    if normalized in {"false", "0", "no", "n", "off"}:
        return "No"
    return None


def _normalize_odbc_connection_string(raw_connection: str) -> str:
    """Normalize SSMS-style connection options for Microsoft ODBC Driver 18."""
    normalized_parts: list[str] = []

    for raw_part in str(raw_connection).split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue

        key, value = (item.strip() for item in part.split("=", 1))
        lookup = key.casefold()

        if lookup in {"pooling", "persist security info", "command timeout"}:
            continue

        if lookup == "data source":
            key = "Server"
        elif lookup == "initial catalog":
            key = "Database"
        elif lookup == "integrated security":
            key = "Trusted_Connection"
            value = _odbc_boolean(value) or value
        elif lookup == "multipleactiveresultsets":
            key = "MARS_Connection"
            value = _odbc_boolean(value) or value
        elif lookup == "application name":
            key = "APP"
        elif lookup == "encrypt":
            key = "Encrypt"
            value = _odbc_boolean(value) or value
        elif lookup == "trustservercertificate":
            key = "TrustServerCertificate"
            value = _odbc_boolean(value) or value
        elif lookup == "trusted_connection":
            key = "Trusted_Connection"
            value = _odbc_boolean(value) or value
        elif lookup == "mars_connection":
            key = "MARS_Connection"
            value = _odbc_boolean(value) or value

        normalized_parts.append(f"{key}={value}")

    return ";".join(normalized_parts)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create and cache the SQLAlchemy engine used by the application."""
    odbc = os.getenv("SQL_SERVER_ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    connection_options = _normalize_odbc_connection_string(SQL_SERVER_CONNECTION)
    connection = f"DRIVER={{{odbc}}};{connection_options}"
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


def _normalize_learning_value(value: Any) -> Any:
    """Normalize structured learning data before comparison and persistence.

    Empty optional values are removed from dictionaries so semantically equal
    results such as ``{"title": null}`` and a missing ``title`` field compare
    as the same learning example. Numeric zero and ``False`` are preserved.
    """
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if item is None or item == "":
                continue
            normalized_item = _normalize_learning_value(item)
            if isinstance(normalized_item, dict) and not normalized_item:
                continue
            normalized[str(key)] = normalized_item
        return normalized
    if isinstance(value, list):
        return [_normalize_learning_value(item) for item in value]
    return value


def _canonical_json(value: dict[str, Any]) -> str:
    """Serialize structured learning data deterministically for comparison."""
    normalized = _normalize_learning_value(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def get_or_create_user_id(external_user_id: str | None) -> str:
    """Resolve an external user identifier to ``users.id``."""
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


def _learning_example_exists(
    conn: Connection,
    database_user_id: str,
    normalized_message: str,
    result_json: str,
    corrected: bool,
) -> bool:
    """Check whether an equivalent learning example already exists.

    Existing rows may have been serialized with different whitespace, key order
    or explicit null fields, so JSON is normalized in Python before comparison.
    For a raw candidate (``corrected = 0``), an equivalent verified example also
    counts as a duplicate: once a result is trusted, the same interpretation
    should not generate more diagnostic rows.
    """
    corrected_clause = "corrected = 1" if corrected else "corrected IN (0, 1)"
    rows = conn.execute(
        text(f"""
            SELECT result_json
            FROM dbo.learning_examples
            WHERE user_id = :user_id
              AND normalized_message = :normalized_message
              AND {corrected_clause}
        """),
        {
            "user_id": database_user_id,
            "normalized_message": normalized_message,
        },
    ).scalars().all()

    for stored_result_json in rows:
        try:
            stored_canonical = _canonical_json(json.loads(stored_result_json))
        except (TypeError, ValueError, json.JSONDecodeError):
            stored_canonical = str(stored_result_json).strip()
        if stored_canonical == result_json:
            return True
    return False


def _insert_learning_example(
    conn: Connection,
    database_user_id: str,
    message: str,
    result: dict[str, Any],
    corrected: bool,
) -> bool:
    """Insert one learning row unless an equivalent row already exists."""
    normalized_message = " ".join(str(message).lower().split())
    result_json = _canonical_json(result)

    if _learning_example_exists(
        conn,
        database_user_id,
        normalized_message,
        result_json,
        corrected,
    ):
        return False

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
            "result_json": result_json,
            "corrected": corrected,
        },
    )
    return True


def save_learning_example(
    user_id: str,
    message: str,
    result: dict[str, Any],
    corrected: bool = False,
) -> None:
    """Persist one interpreted chat example for the given external user id."""
    database_user_id = get_or_create_user_id(user_id)
    with get_engine().begin() as conn:
        _insert_learning_example(conn, database_user_id, message, result, corrected)


def save_conversation_feedback(
    user_id: str,
    message: str,
    model_result: dict[str, Any],
) -> int:
    """Store feedback candidate and return its database id.

    A row without ``corrected_result_json`` means the interpretation has not
    been verified yet (or has explicitly been rejected and awaits a correction).
    """
    database_user_id = get_or_create_user_id(user_id)
    with get_engine().begin() as conn:
        feedback_id = conn.execute(
            text("""
                INSERT INTO dbo.conversation_feedback (
                    user_id,
                    message,
                    model_result_json,
                    corrected_result_json
                )
                OUTPUT INSERTED.id
                VALUES (
                    :user_id,
                    :message,
                    :model_result_json,
                    NULL
                )
            """),
            {
                "user_id": database_user_id,
                "message": message,
                "model_result_json": _canonical_json(model_result),
            },
        ).scalar_one()
    return int(feedback_id)


def verify_conversation_feedback(
    user_id: str,
    feedback_id: int,
    corrected_result: dict[str, Any],
) -> bool:
    """Attach the verified result and promote it to a trusted learning example."""
    database_user_id = get_or_create_user_id(user_id)
    corrected_json = _canonical_json(corrected_result)

    with get_engine().begin() as conn:
        feedback = conn.execute(
            text("""
                SELECT id, message
                FROM dbo.conversation_feedback WITH (UPDLOCK, HOLDLOCK)
                WHERE id = :feedback_id
                  AND user_id = :user_id
            """),
            {"feedback_id": feedback_id, "user_id": database_user_id},
        ).mappings().one_or_none()

        if feedback is None:
            return False

        conn.execute(
            text("""
                UPDATE dbo.conversation_feedback
                SET corrected_result_json = :corrected_result_json
                WHERE id = :feedback_id
                  AND user_id = :user_id
            """),
            {
                "feedback_id": feedback_id,
                "user_id": database_user_id,
                "corrected_result_json": corrected_json,
            },
        )
        _insert_learning_example(
            conn,
            database_user_id,
            str(feedback["message"]),
            corrected_result,
            corrected=True,
        )
    return True


def find_learning_examples(
    user_id: str,
    message: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Find similar, explicitly verified examples for the same user."""
    tokens = set(" ".join(str(message).lower().split()).split())
    if not tokens:
        return []

    database_user_id = get_or_create_user_id(user_id)
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT TOP 50 id, message, normalized_message, result_json, corrected
                FROM dbo.learning_examples
                WHERE user_id = :user_id
                  AND corrected = 1
                ORDER BY created_at DESC
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

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in scored[:limit]]


def format_learning_examples(examples: list[dict[str, Any]]) -> str:
    """Render verified examples as few-shot context for the LLM."""
    if not examples:
        return ""

    lines = ["\nZWERYFIKOWANE PRZYKŁADY Z POPRZEDNICH INTERAKCJI:"]
    for example in examples:
        lines.append(f"UŻYTKOWNIK: {example['message']}")
        lines.append(f"POPRAWNY JSON: {json.dumps(example['result'], ensure_ascii=False)}")
    return "\n".join(lines) + "\n"
