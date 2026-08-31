"""Streamlit dashboard frontend for the OrganizerAI conversational calendar."""

from __future__ import annotations

import html
import os
from datetime import datetime
from uuid import uuid4

import pandas as pd
import requests
import streamlit as st

from motivation_ui import (
    render_due_motivation_reminders,
    render_reflection_reminder_offer,
)
from ui_theme import inject_dashboard_css


API_URL = os.getenv("ORGANIZER_API_URL", "http://127.0.0.1:8001").rstrip("/")
USER_ID = "local-user"
FEEDBACK_STATUSES = {
    "ready_for_confirmation",
    "calendar_search",
    "calendar_delete_confirmation",
}

NAV_ITEMS = (
    ("Rozmowa", "💬"),
    ("Podsumowanie", "📊"),
    ("Kalendarz", "📅"),
    ("Refleksje", "⭐"),
    ("Remindery", "🔔"),
    ("Historia", "🕘"),
    ("Ustawienia", "⚙️"),
)

PAGE_TITLES = {
    "Rozmowa": ("Asystent organizacji czasu", "Zaplanuj, wyszukaj lub usuń wydarzenie w naturalnej rozmowie."),
    "Podsumowanie": ("Podsumowanie", "Zobacz swoją aktywność, refleksje i sposób korzystania z OrganizerAI."),
    "Kalendarz": ("Kalendarz", "Najbliższe wydarzenia pobrane z Google Calendar."),
    "Refleksje": ("Refleksje po wydarzeniach", "Oceń zakończone aktywności i wykorzystaj wynik do personalizacji."),
    "Remindery": ("Remindery motywacyjne", "Zarządzaj przypomnieniami utworzonymi po pozytywnie ocenionych aktywnościach."),
    "Historia": ("Historia rozmowy", "Przegląd bieżącej sesji konwersacyjnej."),
    "Ustawienia": ("Ustawienia i diagnostyka", "Podstawowe informacje o połączeniach i bieżącej sesji."),
}


st.set_page_config(
    page_title="OrganizerAI",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)
inject_dashboard_css()


def _post_json(path: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(f"{API_URL}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _get_json(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    response = requests.get(f"{API_URL}{path}", params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _feedback_candidate(user_message: str, response_data: dict) -> dict | None:
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


def _format_event_time_range(event: dict) -> str:
    start = _format_calendar_datetime(event.get("start"))
    end = _format_calendar_datetime(event.get("end"))
    if start == "?" and end == "?":
        return "Termin nieznany"
    if end == "?":
        return start
    return f"{start} – {end}"


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

    st.markdown('<div class="oa-panel-title">👍 Informacja zwrotna</div>', unsafe_allow_html=True)
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
    st.markdown('<div class="oa-panel-title">⭐ Oceń ostatnie wydarzenia</div>', unsafe_allow_html=True)
    st.caption(
        "Wybierz zakończone wydarzenie i opisz własnymi słowami, jak je oceniasz. "
        "Mistral analizuje opinię, a wynik jest zapisywany jako osobna refleksja."
    )

    refresh_col, info_col = st.columns([1, 2])
    with refresh_col:
        if st.button(
            "🔄 Pobierz zakończone",
            use_container_width=True,
            key="load_completed_events",
        ):
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
        key=f"reflection_feedback_text_{selected_id}",
    )
    rating_choice = st.selectbox(
        "Ocena 1–5 (opcjonalnie)",
        options=["Nie podaję", 1, 2, 3, 4, 5],
        key=f"reflection_rating_{selected_id}",
    )

    if st.button(
        "🧠 Przeanalizuj i zapisz ocenę",
        use_container_width=True,
        key="save_reflection",
        type="primary",
    ):
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
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Nie udało się przeanalizować lub zapisać oceny: {exc}")


def _init_session_state() -> None:
    defaults = (
        ("messages", []),
        ("draft_event", None),
        ("feedback_candidate", None),
        ("pending_feedback_id", None),
        ("feedback_notice", None),
        ("session_id", str(uuid4())),
        ("completed_events", []),
        ("last_reflection", None),
        ("reminder_consent_reflection_id", None),
        ("active_page", "Rozmowa"),
    )
    for key, default in defaults:
        if key not in st.session_state:
            st.session_state[key] = default


def _api_connected() -> bool:
    try:
        response = requests.get(f"{API_URL}/", timeout=1.5)
        return response.ok
    except requests.RequestException:
        return False


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="oa-sidebar-brand">
                <strong>OrganizerAI</strong>
                <div>Asystent organizacji czasu</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        for page, icon in NAV_ITEMS:
            active = st.session_state.active_page == page
            if st.button(
                f"{icon}  {page}",
                key=f"nav_{page}",
                use_container_width=True,
                type="primary" if active else "secondary",
            ):
                st.session_state.active_page = page
                st.rerun()

        st.markdown("---")
        status = "● API połączone" if _api_connected() else "● API offline"
        st.caption(status)
        st.caption(f"Użytkownik: {USER_ID}")


def _render_header() -> None:
    title, subtitle = PAGE_TITLES[st.session_state.active_page]
    connected = _api_connected()
    status_class = "ok" if connected else "off"
    status_text = "● Połączono z API" if connected else "● Brak połączenia z API"

    st.markdown(
        f"""
        <div class="oa-header">
            <div>
                <h1>{html.escape(title)}</h1>
                <div class="oa-subtitle">{html.escape(subtitle)}</div>
            </div>
            <div class="oa-status {status_class}">{html.escape(status_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_event_summary_card(event: dict) -> None:
    title = html.escape(str(event.get("title") or "Bez tytułu"))
    date_hint = html.escape(str(event.get("date_hint") or "—"))
    time_hint = html.escape(str(event.get("time_hint") or "—"))
    duration = event.get("duration_minutes")
    duration_text = f"{duration} min" if duration else "—"

    st.markdown(
        f"""
        <div class="oa-card oa-event-summary">
            <div class="oa-card-title">Podsumowanie wydarzenia</div>
            <div class="oa-card-meta"><b>Tytuł:</b> {title}</div>
            <div class="oa-card-meta"><b>Data:</b> {date_hint}</div>
            <div class="oa-card-meta"><b>Godzina:</b> {time_hint}</div>
            <div class="oa-card-meta"><b>Czas trwania:</b> {html.escape(duration_text)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _process_chat_message(prompt: str) -> None:
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
                "status": status,
                "event": data.get("event"),
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

    except requests.RequestException as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"Nie udało się połączyć z API: {exc}",
                "status": "error",
            }
        )
    except ValueError:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": "API zwróciło niepoprawną odpowiedź.",
                "status": "error",
            }
        )


def _render_chat_history() -> None:
    messages = st.session_state.messages
    if not messages:
        st.markdown(
            """
            <div class="oa-card">
                <div class="oa-card-title">Zacznij rozmowę</div>
                <div class="oa-card-meta">
                    Możesz napisać np. „Dodaj trening w sobotę o 12 na 90 minut”,
                    „Co mam jutro?” albo „Usuń dentystę w poniedziałek”.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for index, message in enumerate(messages):
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

            is_latest = index == len(messages) - 1
            if (
                is_latest
                and message["role"] == "assistant"
                and message.get("status") == "ready_for_confirmation"
                and isinstance(message.get("event"), dict)
            ):
                _render_event_summary_card(message["event"])
                save_col, cancel_col = st.columns(2)
                with save_col:
                    if st.button(
                        "✅ Tak, zapisz",
                        key="confirm_create_from_card",
                        use_container_width=True,
                        type="primary",
                    ):
                        _process_chat_message("tak")
                        st.rerun()
                with cancel_col:
                    if st.button(
                        "✕ Anuluj",
                        key="cancel_create_from_card",
                        use_container_width=True,
                    ):
                        _process_chat_message("anuluj")
                        st.rerun()


def _load_upcoming_events(limit: int = 10, days: int = 30) -> list[dict]:
    data = _get_json(
        "/events/upcoming",
        params={"limit": limit, "days": days},
        timeout=30,
    )
    return data.get("events") or []


def _load_pending_reminders(limit: int = 20) -> list[dict]:
    data = _get_json(
        "/motivation-reminders",
        params={"user_id": USER_ID, "limit": limit},
        timeout=30,
    )
    return data.get("reminders") or []


def _render_upcoming_panel(limit: int = 4) -> None:
    st.markdown('<div class="oa-panel-title">📅 Nadchodzące wydarzenia</div>', unsafe_allow_html=True)
    try:
        events = _load_upcoming_events(limit=limit, days=30)
    except requests.RequestException:
        st.markdown('<div class="oa-empty">Nie udało się pobrać kalendarza.</div>', unsafe_allow_html=True)
        return

    if not events:
        st.markdown('<div class="oa-empty">Brak wydarzeń w najbliższym okresie.</div>', unsafe_allow_html=True)
    else:
        for event in events:
            title = html.escape(str(event.get("title") or "(bez tytułu)"))
            when = html.escape(_format_event_time_range(event))
            st.markdown(
                f"""
                <div class="oa-card">
                    <div class="oa-card-title">{title}</div>
                    <div class="oa-card-meta">{when}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if st.button("Pokaż cały kalendarz", key="open_calendar_page", use_container_width=True):
        st.session_state.active_page = "Kalendarz"
        st.rerun()


def _render_reminder_panel(limit: int = 3) -> None:
    st.markdown('<div class="oa-panel-title">🔔 Remindery motywacyjne</div>', unsafe_allow_html=True)
    try:
        reminders = _load_pending_reminders(limit=limit)
    except requests.RequestException:
        st.markdown('<div class="oa-empty">Nie udało się pobrać reminderów.</div>', unsafe_allow_html=True)
        reminders = []

    if reminders:
        for reminder in reminders:
            title = html.escape(str(reminder.get("event_title") or "Aktywność"))
            remind_at = html.escape(_format_calendar_datetime(reminder.get("remind_at")))
            st.markdown(
                f"""
                <div class="oa-card">
                    <div class="oa-card-title">{title}</div>
                    <div class="oa-card-meta">{remind_at}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.markdown('<div class="oa-empty">Brak aktywnych reminderów.</div>', unsafe_allow_html=True)

    render_due_motivation_reminders(API_URL, USER_ID)

    if st.button("Zarządzaj reminderami", key="open_reminders_page", use_container_width=True):
        st.session_state.active_page = "Remindery"
        st.rerun()


def _render_chat_page() -> None:
    chat_col, side_col = st.columns([2.2, 0.9], gap="large")

    with chat_col:
        _render_chat_history()
        _render_feedback_controls()

        if st.session_state.pending_feedback_id and not st.session_state.feedback_candidate:
            st.info("Czekam na poprawkę poprzedniej interpretacji. Napisz ją normalnie w czacie.")

        prompt = st.chat_input("Napisz wiadomość...")
        if prompt:
            _process_chat_message(prompt)
            st.rerun()

    with side_col:
        _render_upcoming_panel(limit=4)
        st.markdown('<div class="oa-section-spacer"></div>', unsafe_allow_html=True)
        _render_reminder_panel(limit=2)


def _render_calendar_page() -> None:
    refresh_col, info_col = st.columns([1, 3])
    with refresh_col:
        if st.button("🔄 Odśwież", key="refresh_calendar", use_container_width=True):
            st.rerun()
    with info_col:
        st.caption("Widok pokazuje wydarzenia z Google Calendar z najbliższych 60 dni.")

    try:
        events = _load_upcoming_events(limit=50, days=60)
    except requests.RequestException as exc:
        st.error(f"Nie udało się pobrać wydarzeń: {exc}")
        return

    if not events:
        st.info("Brak nadchodzących wydarzeń.")
        return

    for event in events:
        title = html.escape(str(event.get("title") or "(bez tytułu)"))
        when = html.escape(_format_event_time_range(event))
        description = html.escape(str(event.get("description") or "").strip())
        description_html = (
            f'<div class="oa-card-meta">{description}</div>' if description else ""
        )
        st.markdown(
            f"""
            <div class="oa-card">
                <div class="oa-card-title">{title}</div>
                <div class="oa-card-meta">{when}</div>
                {description_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if event.get("calendar_link"):
            st.link_button(
                "Otwórz w Google Calendar",
                event["calendar_link"],
                key=f"calendar_event_{event.get('id')}",
            )


def _render_reflections_page() -> None:
    _render_event_reflections()
    st.divider()
    render_reflection_reminder_offer(API_URL, USER_ID)


def _render_reminders_page() -> None:
    try:
        reminders = _load_pending_reminders(limit=50)
    except requests.RequestException as exc:
        st.error(f"Nie udało się pobrać reminderów: {exc}")
        reminders = []

    if reminders:
        st.markdown('<div class="oa-panel-title">Zaplanowane przypomnienia</div>', unsafe_allow_html=True)
        for reminder in reminders:
            title = html.escape(str(reminder.get("event_title") or "Aktywność"))
            remind_at = html.escape(_format_calendar_datetime(reminder.get("remind_at")))
            st.markdown(
                f"""
                <div class="oa-card">
                    <div class="oa-card-title">{title}</div>
                    <div class="oa-card-meta">Termin: {remind_at}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    else:
        st.info("Nie masz obecnie zaplanowanych reminderów motywacyjnych.")

    st.divider()
    render_due_motivation_reminders(API_URL, USER_ID)


def _load_summary(days: int) -> dict:
    return _get_json(
        "/summary",
        params={"user_id": USER_ID, "days": days},
        timeout=40,
    )


def _render_summary_page() -> None:
    period_col, refresh_col = st.columns([3, 1])
    with period_col:
        days = st.selectbox(
            "Zakres podsumowania",
            options=[7, 30, 90],
            index=1,
            format_func=lambda value: f"Ostatnie {value} dni",
            key="summary_days",
        )
    with refresh_col:
        st.write("")
        st.write("")
        if st.button("🔄 Odśwież", key="refresh_summary", use_container_width=True):
            st.rerun()

    try:
        summary = _load_summary(days)
    except requests.RequestException as exc:
        st.error(f"Nie udało się pobrać podsumowania: {exc}")
        return

    if not summary.get("calendar_available", True):
        st.warning(
            "Nie udało się pobrać zakończonych wydarzeń z Google Calendar. "
            "Pozostałe dane z refleksji, reminderów i metryk są nadal dostępne."
        )

    overview = summary.get("overview") or {}
    metric_cols = st.columns(5)
    metric_cols[0].metric("Zakończone wydarzenia", overview.get("completed_events", 0))
    metric_cols[1].metric("Refleksje", overview.get("reflections", 0))
    average_rating = overview.get("average_rating")
    metric_cols[2].metric(
        "Średnia ocena",
        f"{average_rating:.2f}/5" if isinstance(average_rating, (int, float)) else "—",
    )
    metric_cols[3].metric("Warto powtórzyć", overview.get("worth_repeating", 0))
    metric_cols[4].metric("Aktywne remindery", overview.get("active_reminders", 0))

    st.divider()
    activity_col, sentiment_col = st.columns(2, gap="large")

    with activity_col:
        st.markdown('<div class="oa-panel-title">📅 Moja aktywność</div>', unsafe_allow_html=True)
        st.caption("Liczba zakończonych wydarzeń w kolejnych tygodniach.")
        weekly = summary.get("weekly_activity") or []
        if weekly:
            activity_df = pd.DataFrame(weekly)
            st.bar_chart(
                activity_df,
                x="label",
                y="count",
                use_container_width=True,
            )
        else:
            st.info("Brak danych o zakończonych wydarzeniach w wybranym okresie.")

    with sentiment_col:
        st.markdown('<div class="oa-panel-title">🙂 Jak oceniałem aktywności?</div>', unsafe_allow_html=True)
        st.caption("Sentyment zapisanych refleksji analizowanych przez moduł NLP.")
        sentiments = summary.get("sentiments") or {}
        sentiment_rows = [
            {"Ocena": "Pozytywne", "Liczba": int(sentiments.get("positive", 0))},
            {"Ocena": "Neutralne", "Liczba": int(sentiments.get("neutral", 0))},
            {"Ocena": "Mieszane", "Liczba": int(sentiments.get("mixed", 0))},
            {"Ocena": "Negatywne", "Liczba": int(sentiments.get("negative", 0))},
        ]
        if any(row["Liczba"] for row in sentiment_rows):
            st.bar_chart(
                pd.DataFrame(sentiment_rows),
                x="Ocena",
                y="Liczba",
                use_container_width=True,
            )
        else:
            st.info("Brak przeanalizowanych refleksji w wybranym okresie.")

    st.divider()
    liked_col, repeat_col = st.columns([1.35, 0.65], gap="large")

    with liked_col:
        st.markdown('<div class="oa-panel-title">⭐ Co najbardziej mi się podobało?</div>', unsafe_allow_html=True)
        top_activities = summary.get("top_activities") or []
        if not top_activities:
            st.info("Dodaj refleksje po wydarzeniach, aby zobaczyć tutaj najlepiej oceniane aktywności.")
        else:
            for item in top_activities:
                title = html.escape(str(item.get("title") or "Aktywność"))
                rating = item.get("average_rating")
                rating_text = f"{rating:.2f}/5" if isinstance(rating, (int, float)) else "bez oceny liczbowej"
                repeat_count = int(item.get("worth_repeating_count") or 0)
                reflection_count = int(item.get("reflection_count") or 0)
                repeat_text = (
                    f" · warto powtórzyć: {repeat_count}×"
                    if repeat_count
                    else ""
                )
                st.markdown(
                    f"""
                    <div class="oa-card">
                        <div class="oa-card-title">{title}</div>
                        <div class="oa-card-meta">
                            Średnia ocena: {html.escape(rating_text)}
                            · refleksje: {reflection_count}{html.escape(repeat_text)}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    with repeat_col:
        st.markdown('<div class="oa-panel-title">🔁 Czy warto powtarzać?</div>', unsafe_allow_html=True)
        repeat = summary.get("worth_repeating") or {}
        st.metric("Tak", int(repeat.get("yes", 0)))
        st.metric("Nie", int(repeat.get("no", 0)))
        st.metric("Brak decyzji", int(repeat.get("unknown", 0)))

    st.divider()
    reminder_col, assistant_col = st.columns(2, gap="large")

    with reminder_col:
        st.markdown('<div class="oa-panel-title">🔔 Moje przypomnienia</div>', unsafe_allow_html=True)
        reminders = summary.get("reminders") or {}
        reminder_metrics = st.columns(2)
        reminder_metrics[0].metric("Aktywne", int(reminders.get("pending", 0)))
        reminder_metrics[1].metric("Wykonane", int(reminders.get("completed", 0)))
        reminder_metrics[0].metric("Dostarczone", int(reminders.get("delivered", 0)))
        reminder_metrics[1].metric("Odrzucone", int(reminders.get("dismissed", 0)))
        st.caption("Statusy dotyczą reminderów utworzonych w wybranym okresie.")

    with assistant_col:
        st.markdown('<div class="oa-panel-title">🤖 Jak korzystam z OrganizerAI?</div>', unsafe_allow_html=True)
        usage = summary.get("assistant_usage") or {}
        first_row = st.columns(3)
        first_row[0].metric("Tury rozmowy", int(usage.get("turns", 0)))
        first_row[1].metric("Sesje", int(usage.get("sessions", 0)))
        first_row[2].metric("Wywołania LLM", int(usage.get("llm_calls", 0)))
        second_row = st.columns(3)
        second_row[0].metric("Tury bez LLM", int(usage.get("no_llm_turns", 0)))
        second_row[1].metric("Wywołania Calendar", int(usage.get("calendar_calls", 0)))
        second_row[2].metric(
            "Śr. czas odpowiedzi",
            f"{float(usage.get('avg_latency_ms') or 0):.0f} ms",
        )

        operations = usage.get("operations") or []
        if operations:
            operation_labels = {
                "create": "CREATE",
                "search": "SEARCH",
                "delete": "DELETE",
                "chat": "CHAT",
                "external_search": "EXTERNAL",
            }
            operation_df = pd.DataFrame(
                [
                    {
                        "Operacja": operation_labels.get(
                            str(item.get("operation") or "chat"),
                            str(item.get("operation") or "chat").upper(),
                        ),
                        "Liczba": int(item.get("count") or 0),
                    }
                    for item in operations
                ]
            )
            st.bar_chart(
                operation_df,
                x="Operacja",
                y="Liczba",
                use_container_width=True,
            )

        clarification_turns = int(usage.get("clarification_turns", 0))
        if clarification_turns:
            st.caption(
                f"W {clarification_turns} turach system poprosił o doprecyzowanie danych "
                "zamiast przyjmować brakujące wartości."
            )


def _clear_conversation() -> None:
    st.session_state.messages = []
    st.session_state.draft_event = None
    st.session_state.feedback_candidate = None
    st.session_state.pending_feedback_id = None
    st.session_state.feedback_notice = None
    st.session_state.session_id = str(uuid4())
    st.session_state.reminder_consent_reflection_id = None


def _render_history_page() -> None:
    if not st.session_state.messages:
        st.info("Bieżąca sesja nie zawiera jeszcze wiadomości.")
    else:
        for index, message in enumerate(st.session_state.messages, start=1):
            role = "Użytkownik" if message["role"] == "user" else "OrganizerAI"
            st.markdown(
                f"""
                <div class="oa-card">
                    <div class="oa-card-title">{index}. {html.escape(role)}</div>
                    <div class="oa-card-meta">{html.escape(str(message.get("content") or ""))}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    if st.button("🗑️ Wyczyść rozmowę", key="clear_history", use_container_width=False):
        _clear_conversation()
        st.rerun()


def _render_settings_page() -> None:
    connected = _api_connected()
    status = "Połączono" if connected else "Brak połączenia"

    st.markdown(
        f"""
        <div class="oa-card">
            <div class="oa-card-title">Backend API</div>
            <div class="oa-card-meta"><b>Status:</b> {html.escape(status)}</div>
            <div class="oa-card-meta"><b>Adres:</b> {html.escape(API_URL)}</div>
        </div>
        <div class="oa-card">
            <div class="oa-card-title">Bieżąca sesja</div>
            <div class="oa-card-meta"><b>Użytkownik:</b> {html.escape(USER_ID)}</div>
            <div class="oa-card-meta"><b>Session ID:</b> {html.escape(st.session_state.session_id)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(
        "Konfiguracja modelu, Google Calendar i SQL Server pozostaje po stronie backendu. "
        "Ten widok celowo nie eksponuje sekretów ani poświadczeń."
    )


_init_session_state()
_render_sidebar()
_render_header()
_render_notice()

page = st.session_state.active_page
if page == "Rozmowa":
    _render_chat_page()
elif page == "Podsumowanie":
    _render_summary_page()
elif page == "Kalendarz":
    _render_calendar_page()
elif page == "Refleksje":
    _render_reflections_page()
elif page == "Remindery":
    _render_reminders_page()
elif page == "Historia":
    _render_history_page()
else:
    _render_settings_page()
