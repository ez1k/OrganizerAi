import streamlit as st
import requests

st.title("AI Organizer")

msg = st.text_input("Co planujesz?")

if st.button("Dodaj"):
    if not msg:
        st.warning("Wpisz coś najpierw")
    else:
        try:
            res = requests.post(
                "http://localhost:8000/chat",
                json={"message": msg}
            )

            st.write("Status:", res.status_code)
            st.write(res.json())

        except Exception as e:
            st.error(f"Błąd: {e}")


if st.button("Pokaż wydarzenia"):
    try:
        res = requests.get("http://localhost:8000/events")

        st.write("Status:", res.status_code)
        st.write(res.json())

    except Exception as e:
        st.error(f"Błąd: {e}")