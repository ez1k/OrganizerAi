import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral"   # or llama3.1 / mistral


def ask_llm(prompt: str) -> str:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False
    }

    response = requests.post(OLLAMA_URL, json=payload)
    response.raise_for_status()

    return response.json()["response"]