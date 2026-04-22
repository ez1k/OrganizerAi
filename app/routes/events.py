from fastapi import APIRouter
from app.database import engine
from sqlalchemy import text

router = APIRouter()

@router.get("/events")
def get_events():
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM events"))
        return [dict(row._mapping) for row in result]