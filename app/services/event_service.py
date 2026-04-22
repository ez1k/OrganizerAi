from app.backend.database import engine
from sqlalchemy import text

def save_event(event: dict):
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO events (title, start_time, end_time, description)
            VALUES (:title, :start, :end, :description)
        """), {
            "title": event.get("title"),
            "start": event.get("start"),
            "end": event.get("end"),
            "description": event.get("description")
        })
        conn.commit()