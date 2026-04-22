import streamlit as st
import requests

st.title("AI Organizer")

msg = st.text_input("Co planujesz?")

if st.button("Dodaj"):
    res = requests.post("http://localhost:8000/chat", json={
        "message": msg
    })
    st.write(res.json())

if st.button("Pokaż wydarzenia"):
    res = requests.get("http://localhost:8000/events")
    st.write(res.json())