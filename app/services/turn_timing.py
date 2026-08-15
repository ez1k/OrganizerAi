"""Per-request component timing for /chat evaluation metrics."""

from contextvars import ContextVar, Token


_CURRENT_TIMING: ContextVar[dict[str, int] | None] = ContextVar(
    "organizer_chat_turn_timing",
    default=None,
)


def start_turn_timing() -> Token:
    """Start an isolated timing bucket for the current request context."""
    return _CURRENT_TIMING.set(
        {
            "llm_latency_ms": 0,
            "calendar_latency_ms": 0,
            "llm_calls": 0,
            "calendar_calls": 0,
        }
    )


def record_component(component: str, latency_ms: int) -> None:
    """Accumulate one measured component call in the active request context."""
    timing = _CURRENT_TIMING.get()
    if timing is None:
        return

    latency = max(0, int(latency_ms))
    if component == "llm":
        timing["llm_latency_ms"] += latency
        timing["llm_calls"] += 1
    elif component == "calendar":
        timing["calendar_latency_ms"] += latency
        timing["calendar_calls"] += 1


def snapshot_turn_timing() -> dict[str, int]:
    """Return a copy of the current request's component measurements."""
    timing = _CURRENT_TIMING.get() or {}
    return {
        "llm_latency_ms": int(timing.get("llm_latency_ms", 0)),
        "calendar_latency_ms": int(timing.get("calendar_latency_ms", 0)),
        "llm_calls": int(timing.get("llm_calls", 0)),
        "calendar_calls": int(timing.get("calendar_calls", 0)),
    }


def reset_turn_timing(token: Token) -> None:
    """Restore the previous context after a request finishes."""
    _CURRENT_TIMING.reset(token)
