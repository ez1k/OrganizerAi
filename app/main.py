from fastapi import FastAPI
from routes import chat, events

app = FastAPI()

# rejestracja endpointów
app.include_router(chat.router)
app.include_router(events.router)

@app.get("/")
def root():
    return {"message": "Time Assistant API działa"}