from fastapi import APIRouter
from app.services.llm_service import ask_llm

router = APIRouter()

@router.post("/chat")
def ChatRequest(prompt: str):
    response = ask_llm(prompt)
    return {"response": response}