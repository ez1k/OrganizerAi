"""Streamlit frontend for the OrganizerAI conversational calendar."""

import requests
import streamlit as st

API_URL = "http://localhost:8000"
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
    status = response_data.get("status")
    event = response_data.get("event")
    if not isinstance(event, dict) or status not in {"ready_for_confirmation", "confirmed"}:
        return None
    title = event.get("title", "")
    start = event.get("start", "")
    end = event.get("end", "")
    if not any((title, start, end)):
        return None
    return f"📅 {title} · {start} → {end}"


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
        _set_notice("success", "Poprawka została zweryfikowana i trafiła do przykładów używanych przez model.")
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
        _set_notice("success", "Interpretacja została zapisana jako zweryfikowany przykład.")

    st.session_state.feedback_candidate = None
    st.session_state.pending_feedback_id = None


def _reject_feedback(candidate: dict) -> None:
    correction_feedback_id = candidate.get("correction_feedback_id")
    if correction_feedback_id:
        st.session_state.pending_feedback_id = correction_feedback_id
        st.session_state.feedback_candidate = None
        _set_notice("warning", "Napisz kolejną poprawkę w czacie. Zapiszemy ją dopiero po Twoim potwierdzeniu.")
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
    _set_notice("warning", "Oznaczyłem interpretację jako błędną. Napisz teraz w czacie, jak powinienem to rozumieć.")


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
        if st.button("👍 Tak, poprawnie", use_container_width=True, key="feedback_accept"):
            try:
                _accept_feedback(candidate)
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Nie udało się zapisać feedbacku: {exc}")
    with no_col:
        if st.button("👎 Nie, poprawię", use_container_width=True, key="feedback_reject"):
            try:
                _reject_feedback(candidate)
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Nie udało się zapisać feedbacku: {exc}")


for key, default in (
    ("messages", []),
    ("draft_event", None),
    ("feedback_candidate", None),
    ("pending_feedback_id", None),
    ("feedback_notice", None),
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

col1, col2 = st.columns(2)

with col1:
    if st.button("🗑️ Wyczyść rozmowę"):
        st.session_state.messages = []
        st.session_state.draft_event = None
        st.session_state.feedback_candidate = None
        st.session_state.pending_feedback_id = None
        st.session_state.feedback_notice = None
        st.rerun()

with col2:
    if st.button("📅 Pokaż wydarzenia"):
        try:
            res = requests.get(f"{API_URL}/events", timeout=30)
            st.json(res.json())
        except requests.RequestException as exc:
            st.error(f"Nie udało się pobrać wydarzeń: {exc}")
