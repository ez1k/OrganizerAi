import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "mistral"


def ask_llm(prompt: str) -> str:
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 200
            }
        },
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    result = data.get("response", "")

    if not result or result.strip() == "":
        raise ValueError("Empty response from Ollama")

    return result