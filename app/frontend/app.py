import requests
import streamlit as st

API_URL = "http://localhost:8000"

st.set_page_config(page_title="AI Organizer", page_icon="🤖")
st.title("AI Organizer 🤖")

if "messages" not in st.session_state:
    st.session_state.messages = []

if "draft_event" not in st.session_state:
    st.session_state.draft_event = None

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input("Co chcesz zaplanować?")

if prompt:
    history = st.session_state.messages.copy()

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        res = requests.post(
            f"{API_URL}/chat",
            json={
                "message": prompt,
                "history": history,
                "draft_event": st.session_state.draft_event,
            },
            timeout=130,
        )
        data = res.json()

        assistant_message = data.get("message", "Brak odpowiedzi.")
        status = data.get("status")

        with st.chat_message("assistant"):
            st.markdown(assistant_message)

            if data.get("event") and status in {"ready_for_confirmation", "confirmed"}:
                event = data["event"]
                st.caption(
                    f"📅 {event.get('title', '')} · "
                    f"{event.get('start', '')} → {event.get('end', '')}"
                )

                if data.get("calendar_link"):
                    st.link_button("Otwórz w Google Calendar", data["calendar_link"])

        st.session_state.messages.append({
            "role": "assistant",
            "content": assistant_message,
        })

        if status == "confirmed" or status == "cancelled":
            st.session_state.draft_event = None
        elif data.get("event"):
            st.session_state.draft_event = data["event"]

    except requests.RequestException as e:
        with st.chat_message("assistant"):
            st.error(f"Nie udało się połączyć z API: {e}")
    except ValueError:
        with st.chat_message("assistant"):
            st.error("API zwróciło niepoprawną odpowiedź.")


st.divider()

col1, col2 = st.columns(2)

with col1:
    if st.button("🗑️ Wyczyść rozmowę"):
        st.session_state.messages = []
        st.session_state.draft_event = None
        st.rerun()

with col2:
    if st.button("📅 Pokaż wydarzenia"):
        try:
            res = requests.get(f"{API_URL}/events", timeout=30)
            st.json(res.json())
        except requests.RequestException as e:
            st.error(f"Nie udało się pobrać wydarzeń: {e}")
