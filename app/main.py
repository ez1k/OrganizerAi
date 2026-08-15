from fastapi import FastAPI

from app.routes import chat_flow, events, feedback, reflections

app = FastAPI()

app.include_router(chat_flow.router)
app.include_router(events.router)
app.include_router(feedback.router)
app.include_router(reflections.router)


@app.get("/")
def root():
    return {"message": "AI Organizer API działa"}
