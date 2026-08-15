"""Streamlit controls for user-approved motivational reminders."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import streamlit as st

WARSAW = ZoneInfo("Europe/Warsaw")


def _post_json(api_url: str, path: str, payload: dict, timeout: int = 30) -> dict:
    response = requests.post(f"{api_url}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _get_json(api_url: str, path: str, params: dict | None = None, timeout: int = 30) -> dict:
    response = requests.get(f"{api_url}{path}", params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def _format_local_datetime(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "?"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=WARSAW)
        else:
            parsed = parsed.astimezone(WARSAW)
        return parsed.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return text


def _response_detail(exc: requests.RequestException) -> str:
    response = getattr(exc, "response", None)
    if response is None:
        return str(exc)
    try:
        payload = response.json()
        return str(payload.get("detail") or payload)
    except ValueError:
        return str(exc)


def render_reflection_reminder_offer(api_url: str, user_id: str) -> None:
    """Ask for reminder consent after a positive or repeat-worthy reflection."""
    reflection = st.session_state.get("last_reflection")
    if not isinstance(reflection, dict) or not reflection.get("id"):
        return

    worth_repeating = reflection.get("worth_repeating")
    sentiment = str(reflection.get("sentiment") or "").lower()
    eligible = worth_repeating is True or (worth_repeating is None and sentiment == "positive")
    if not eligible:
        return

    reflection_id = int(reflection["id"])
    title = str(reflection.get("event_title") or "tej aktywności")
    consent_id = st.session_state.get("reminder_consent_reflection_id")

    st.subheader("💡 Motywacyjne przypomnienie")
    if consent_id != reflection_id:
        if worth_repeating is True:
            st.info(
                f"Wygląda na to, że „{title}” było dla Ciebie warte powtórzenia. "
                "Chcesz, żebym przypomniał Ci o tej aktywności za jakiś czas?"
            )
        else:
            st.info(
                f"Dobrze oceniasz „{title}”. Czy chcesz, żebym po pewnym czasie "
                "przypomniał Ci o możliwości powtórzenia tej aktywności?"
            )

        yes_col, no_col = st.columns(2)
        with yes_col:
            if st.button(
                "✅ Tak, przypomnij",
                use_container_width=True,
                key=f"reminder_consent_yes_{reflection_id}",
            ):
                st.session_state.reminder_consent_reflection_id = reflection_id
                st.rerun()
        with no_col:
            if st.button(
                "Nie, bez przypomnienia",
                use_container_width=True,
                key=f"reminder_consent_no_{reflection_id}",
            ):
                st.session_state.last_reflection = None
                st.session_state.reminder_consent_reflection_id = None
                st.session_state.feedback_notice = {
                    "kind": "info",
                    "message": "OK, nie ustawiam przypomnienia dla tego wydarzenia.",
                }
                st.rerun()
        return

    st.info("Po jakim czasie mam Ci o tym przypomnieć?")
    when_text = st.text_input(
        "Termin przypomnienia",
        placeholder="Np. za 2 tygodnie, za miesiąc albo za 2 minuty",
        key=f"reminder_when_{reflection_id}",
    )
    st.caption(
        "Termin jest interpretowany deterministycznie. Nieprecyzyjne określenia typu „kiedyś” nie są zapisywane."
    )

    schedule_col, cancel_col = st.columns(2)
    with schedule_col:
        if st.button(
            "⏰ Ustaw przypomnienie",
            use_container_width=True,
            key=f"schedule_reminder_{reflection_id}",
        ):
            if not str(when_text or "").strip():
                st.warning("Napisz, za jaki czas mam przypomnieć.")
                return
            try:
                data = _post_json(
                    api_url,
                    f"/reflections/{reflection_id}/reminders/from-text",
                    {"when_text": when_text, "user_id": user_id},
                )
                reminder = data.get("reminder") or {}
                st.session_state.last_reflection = None
                st.session_state.reminder_consent_reflection_id = None
                st.session_state.feedback_notice = {
                    "kind": "success",
                    "message": (
                        "Przypomnienie zostało ustawione na "
                        f"{_format_local_datetime(reminder.get('remind_at'))}."
                    ),
                }
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Nie udało się ustawić przypomnienia: {_response_detail(exc)}")

    with cancel_col:
        if st.button(
            "Anuluj",
            use_container_width=True,
            key=f"cancel_reminder_setup_{reflection_id}",
        ):
            st.session_state.last_reflection = None
            st.session_state.reminder_consent_reflection_id = None
            st.rerun()


def render_due_motivation_reminders(api_url: str, user_id: str) -> None:
    """Show due reminders and bridge accepted suggestions into safe CREATE."""
    try:
        data = _get_json(
            api_url,
            "/motivation-reminders/due",
            params={"user_id": user_id, "limit": 10},
        )
    except requests.RequestException:
        return

    reminders = data.get("reminders") or []
    if not reminders:
        return

    st.subheader("🔔 Przypomnienia motywacyjne")
    for reminder in reminders:
        reminder_id = int(reminder["id"])
        title = str(reminder.get("event_title") or "wcześniej dobrze ocenionej aktywności")
        st.info(
            f"Ostatnio dobrze wspominałeś „{title}”. Minął ustalony czas. "
            "Chcesz zaplanować podobną aktywność ponownie?"
        )

        plan_col, dismiss_col = st.columns(2)
        with plan_col:
            if st.button(
                "📅 Zaplanuj ponownie",
                use_container_width=True,
                key=f"motivation_plan_{reminder_id}",
            ):
                if st.session_state.get("draft_event"):
                    st.warning(
                        "Najpierw zakończ lub anuluj bieżącą operację kalendarza w czacie. "
                        "Nie nadpisuję aktywnego draftu."
                    )
                    continue
                try:
                    _post_json(
                        api_url,
                        f"/motivation-reminders/{reminder_id}/status",
                        {"status": "completed", "user_id": user_id},
                    )
                    st.session_state.draft_event = {
                        "operation": "create",
                        "title": title,
                    }
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": (
                                f"Jasne — możemy ponownie zaplanować „{title}”. "
                                "Podaj dzień, godzinę rozpoczęcia i czas trwania, "
                                "np. „jutro o 18 na 60 min”."
                            ),
                        }
                    )
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Nie udało się obsłużyć przypomnienia: {_response_detail(exc)}")

        with dismiss_col:
            if st.button(
                "Nie chcę teraz planować",
                use_container_width=True,
                key=f"motivation_dismiss_{reminder_id}",
            ):
                try:
                    _post_json(
                        api_url,
                        f"/motivation-reminders/{reminder_id}/status",
                        {"status": "dismissed", "user_id": user_id},
                    )
                    st.rerun()
                except requests.RequestException as exc:
                    st.error(f"Nie udało się zamknąć przypomnienia: {_response_detail(exc)}")
