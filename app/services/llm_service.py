import requests

OLLAMA_URL = "http://localhost:11434/api/generate"

def ask_llm(prompt: str):
    response = requests.post(OLLAMA_URL, json={
        "model": "mistral",
        "prompt": prompt,
        "stream": False
    })
    return response.json()["response"]