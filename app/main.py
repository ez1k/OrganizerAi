from fastapi import FastAPI
from app.routes import chat, events

app = FastAPI()

app.include_router(chat.router)
app.include_router(events.router)


@app.get("/")
def root():
    return {"message": "Time Assistant API działa"}