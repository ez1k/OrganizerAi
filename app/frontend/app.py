"""Streamlit frontend for the OrganizerAI conversational calendar."""

import os
from datetime import datetime
from uuid import uuid4

import requests
import streamlit as st

API_URL = os.getenv("ORGANIZER_API_URL", "http://127.0.0.1:8001").rstrip("/")
USER_ID = "local-user"
FEEDBACK_STATUSES = {
    "ready_for_confirmation",
    "calendar_search",
    "calendar_delete_confirmation",
}

st.set_page_config(page_title="AI Organizer", page_icon="🤖")
st.title("AI Organizer 🤖")


def _post_json(path: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(f"{API_URL}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _get_json(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    response = requests.get(f"{API_URL}{path}", params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _feedback_candidate(user_message: str, response_data: dict) -> dict | None:
    """Build a feedback candidate only for structured calendar interpretations."""
    status = response_data.get("status")
    result = response_data.get("event")
    if status not in FEEDBACK_STATUSES or not isinstance(result, dict):
        return None
    if result.get("operation") not in {"create", "search", "delete"}:
        return None
    return {
        "message": user_message,
        "result": result,
        "correction_feedback_id": None,
    }


def _event_caption(response_data: dict) -> str | None:
    """Render either a persisted event or the currently collected CREATE slots."""
    status = response_data.get("status")
    event = response_data.get("event")
    if not isinstance(event, dict) or status not in {
        "needs_input",
        "ready_for_confirmation",
        "confirmed",
    }:
        return None

    title = str(event.get("title") or "").strip()
    start = str(event.get("start") or "").strip()
    end = str(event.get("end") or "").strip()

    if start or end:
        parts = [value for value in (title, start, end) if value]
        return "📅 " + " · ".join(parts) if parts else None

    parts = []
    if title:
        parts.append(title)
    if event.get("date_hint"):
        parts.append(str(event["date_hint"]))
    if event.get("time_hint"):
        parts.append(str(event["time_hint"]))
    if event.get("duration_minutes"):
        parts.append(f"{event['duration_minutes']} min")

    return "📅 " + " · ".join(parts) if parts else None


def _format_calendar_datetime(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "?"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return text


def _set_notice(kind: str, message: str) -> None:
    st.session_state.feedback_notice = {"kind": kind, "message": message}


def _render_notice() -> None:
    notice = st.session_state.pop("feedback_notice", None)
    if not notice:
        return
    if notice["kind"] == "success":
        st.success(notice["message"])
    elif notice["kind"] == "warning":
        st.warning(notice["message"])
    else:
        st.info(notice["message"])


def _accept_feedback(candidate: dict) -> None:
    correction_feedback_id = candidate.get("correction_feedback_id")
    if correction_feedback_id:
        _post_json(
            f"/feedback/{correction_feedback_id}/correction",
            {
                "user_id": USER_ID,
                "corrected_result": candidate["result"],
            },
        )
        _set_notice(
            "success",
            "Poprawka została zweryfikowana i trafiła do przykładów używanych przez model.",
        )
    else:
        _post_json(
            "/feedback",
            {
                "user_id": USER_ID,
                "message": candidate["message"],
                "result": candidate["result"],
                "accepted": True,
            },
        )
        _set_notice(
            "success",
            "Interpretacja została zapisana jako zweryfikowany przykład.",
        )

    st.session_state.feedback_candidate = None
    st.session_state.pending_feedback_id = None


def _reject_feedback(candidate: dict) -> None:
    correction_feedback_id = candidate.get("correction_feedback_id")
    if correction_feedback_id:
        st.session_state.pending_feedback_id = correction_feedback_id
        st.session_state.feedback_candidate = None
        _set_notice(
            "warning",
            "Napisz kolejną poprawkę w czacie. Zapiszemy ją dopiero po Twoim potwierdzeniu.",
        )
        return

    data = _post_json(
        "/feedback",
        {
            "user_id": USER_ID,
            "message": candidate["message"],
            "result": candidate["result"],
            "accepted": False,
        },
    )
    st.session_state.pending_feedback_id = data["feedback_id"]
    st.session_state.feedback_candidate = None
    _set_notice(
        "warning",
        "Oznaczyłem interpretację jako błędną. Napisz teraz w czacie, jak powinienem to rozumieć.",
    )


def _render_feedback_controls() -> None:
    candidate = st.session_state.get("feedback_candidate")
    if not candidate:
        return

    if candidate.get("correction_feedback_id"):
        st.caption("Czy po tej poprawce dobrze rozumiem Twoją intencję?")
    else:
        st.caption("Czy dobrze zrozumiałem tę wiadomość?")

    yes_col, no_col = st.columns(2)
    with yes_col:
        if st.button(
            "👍 Tak, poprawnie",
            use_container_width=True,
            key="feedback_accept",
        ):
            try:
                _accept_feedback(candidate)
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Nie udało się zapisać feedbacku: {exc}")
    with no_col:
        if st.button(
            "👎 Nie, poprawię",
            use_container_width=True,
            key="feedback_reject",
        ):
            try:
                _reject_feedback(candidate)
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Nie udało się zapisać feedbacku: {exc}")


def _load_completed_events() -> None:
    data = _get_json(
        "/events/completed",
        params={"user_id": USER_ID, "days": 14, "limit": 20},
        timeout=30,
    )
    st.session_state.completed_events = data.get("events", [])


def _render_event_reflections() -> None:
    st.subheader("⭐ Oceń ostatnie wydarzenia")
    st.caption(
        "Wybierz zakończone wydarzenie i opisz własnymi słowami, jak je oceniasz. "
        "Mistral analizuje opinię, a wynik jest zapisywany jako osobna refleksja."
    )

    refresh_col, info_col = st.columns([1, 2])
    with refresh_col:
        if st.button("🔄 Pobierz zakończone", use_container_width=True, key="load_completed_events"):
            try:
                _load_completed_events()
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Nie udało się pobrać zakończonych wydarzeń: {exc}")
    with info_col:
        st.caption("Pokazywane są wydarzenia zakończone w ciągu ostatnich 14 dni.")

    events = st.session_state.get("completed_events", [])
    if not events:
        st.info("Kliknij „Pobierz zakończone”, aby załadować wydarzenia z Google Calendar.")
        return

    unrated = [event for event in events if not event.get("reflected")]
    rated_count = len(events) - len(unrated)
    if rated_count:
        st.caption(f"Już ocenione wydarzenia: {rated_count}.")

    if not unrated:
        st.success("Wszystkie pobrane zakończone wydarzenia mają już zapisaną ocenę.")
        return

    labels = {}
    for event in unrated:
        event_id = str(event.get("id") or "")
        label = (
            f"{event.get('title') or '(bez tytułu)'} — "
            f"{_format_calendar_datetime(event.get('start'))}"
        )
        labels[event_id] = label

    selected_id = st.selectbox(
        "Wydarzenie",
        options=list(labels),
        format_func=lambda event_id: labels[event_id],
        key="reflection_event_id",
    )
    selected = next(event for event in unrated if str(event.get("id")) == selected_id)
    st.caption(
        f"{_format_calendar_datetime(selected.get('start'))} – "
        f"{_format_calendar_datetime(selected.get('end'))}"
    )

    feedback_text = st.text_area(
        "Jak oceniasz to wydarzenie?",
        placeholder="Np. Było super, dobrze odpocząłem i chętnie zrobiłbym to ponownie.",
        key="reflection_feedback_text",
    )
    rating_choice = st.selectbox(
        "Ocena 1–5 (opcjonalnie)",
        options=["Nie podaję", 1, 2, 3, 4, 5],
        key="reflection_rating",
    )

    if st.button("🧠 Przeanalizuj i zapisz ocenę", use_container_width=True, key="save_reflection"):
        if not str(feedback_text or "").strip():
            st.warning("Najpierw napisz krótką opinię o wydarzeniu.")
            return

        try:
            analyzed = _post_json(
                "/reflections/analyze",
                {"feedback_text": feedback_text, "user_id": USER_ID},
                timeout=130,
            )
            analysis = analyzed.get("analysis") or {}
            rating = rating_choice if isinstance(rating_choice, int) else analysis.get("rating")

            saved = _post_json(
                "/reflections",
                {
                    "calendar_event_id": selected["id"],
                    "event_title": selected.get("title") or "(bez tytułu)",
                    "event_start": selected["start"],
                    "event_end": selected["end"],
                    "rating": rating,
                    "sentiment": analysis.get("sentiment"),
                    "feedback_text": feedback_text,
                    "worth_repeating": analysis.get("worth_repeating"),
                    "user_id": USER_ID,
                },
                timeout=30,
            )
            reflection = saved.get("reflection") or {}
            st.session_state.last_reflection = {
                **reflection,
                "analysis_summary": analysis.get("summary"),
                "confidence": analysis.get("confidence"),
            }

            for event in st.session_state.completed_events:
                if str(event.get("id")) == selected_id:
                    event["reflected"] = True

            if analysis.get("worth_repeating") is True:
                _set_notice(
                    "success",
                    "Ocena została zapisana. To wydarzenie wygląda na warte powtórzenia — możemy teraz ustalić, kiedy mam o nim przypomnieć.",
                )
            else:
                _set_notice("success", "Ocena wydarzenia została zapisana.")
            st.session_state.reflection_feedback_text = ""
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Nie udało się przeanalizować lub zapisać oceny: {exc}")


for key, default in (
    ("messages", []),
    ("draft_event", None),
    ("feedback_candidate", None),
    ("pending_feedback_id", None),
    ("feedback_notice", None),
    ("session_id", str(uuid4())),
    ("completed_events", []),
    ("last_reflection", None),
):
    if key not in st.session_state:
        st.session_state[key] = default

_render_notice()

for index, message in enumerate(st.session_state.messages):
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("caption"):
            st.caption(message["caption"])
        if message.get("calendar_link"):
            st.link_button(
                "Otwórz w Google Calendar",
                message["calendar_link"],
                key=f"calendar_link_{index}",
            )

_render_feedback_controls()

if st.session_state.pending_feedback_id and not st.session_state.feedback_candidate:
    st.info("Czekam na poprawkę poprzedniej interpretacji. Napisz ją normalnie w czacie.")

prompt = st.chat_input("Co chcesz zaplanować?")

if prompt:
    history = [
        {"role": item["role"], "content": item["content"]}
        for item in st.session_state.messages
    ]
    st.session_state.feedback_candidate = None

    st.session_state.messages.append({"role": "user", "content": prompt})

    try:
        data = _post_json(
            "/chat",
            {
                "message": prompt,
                "history": history,
                "draft_event": st.session_state.draft_event,
                "user_id": USER_ID,
                "session_id": st.session_state.session_id,
            },
            timeout=130,
        )

        assistant_message = data.get("message", "Brak odpowiedzi.")
        status = data.get("status")
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": assistant_message,
                "caption": _event_caption(data),
                "calendar_link": data.get("calendar_link"),
            }
        )

        candidate = _feedback_candidate(prompt, data)
        if candidate:
            if st.session_state.pending_feedback_id:
                candidate["correction_feedback_id"] = st.session_state.pending_feedback_id
                st.session_state.pending_feedback_id = None
            st.session_state.feedback_candidate = candidate

        if status in {"confirmed", "cancelled"}:
            st.session_state.draft_event = None
            st.session_state.feedback_candidate = None
            st.session_state.pending_feedback_id = None
        elif data.get("event"):
            st.session_state.draft_event = data["event"]

        st.rerun()

    except requests.RequestException as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"Nie udało się połączyć z API: {exc}",
            }
        )
        st.rerun()
    except ValueError:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "API zwróciło niepoprawną odpowiedź.",
            }
        )
        st.rerun()


st.divider()
_render_event_reflections()

st.divider()

col1, col2 = st.columns(2)

with col1:
    if st.button("🗑️ Wyczyść rozmowę"):
        st.session_state.messages = []
        st.session_state.draft_event = None
        st.session_state.feedback_candidate = None
        st.session_state.pending_feedback_id = None
        st.session_state.feedback_notice = None
        st.session_state.session_id = str(uuid4())
        st.rerun()

with col2:
    if st.button("📅 Pokaż wydarzenia"):
        try:
            res = requests.get(f"{API_URL}/events", timeout=30)
            st.json(res.json())
        except requests.RequestException as exc:
            st.error(f"Nie udało się pobrać wydarzeń: {exc}")