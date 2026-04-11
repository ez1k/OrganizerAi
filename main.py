from fastapi import FastAPI
from app.routes import tasks

app = FastAPI()

app.include_router(tasks.router)

@app.get("/")
def root():
    return {"message": "Time Assistant API"}