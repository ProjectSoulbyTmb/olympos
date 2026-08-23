import json
import os
import re
import urllib.error
import urllib.request


class LLMClient:
    def __init__(self, model=None, base_url=None, api_key=None,
                 temperature=0.4, max_tokens=900, timeout=600):
        self.model = model or os.environ.get("LLM_MODEL", "llama3.1:8b")
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL",
                         "http://localhost:11434/v1")).rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "ollama")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    def chat(self, system, user):
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"could not reach LLM at {self.base_url}: {e}. "
                "Start Ollama (ollama serve) or set LLM_BASE_URL/LLM_API_KEY."
            ) from e
        return data["choices"][0]["message"]["content"]


def extract_code(text):
    blocks = re.findall(r"```[a-zA-Z]*\s*\n(.*?)(?:```|\Z)", text, re.DOTALL)
    for block in reversed(blocks):
        block = block.strip()
        if "def run(" in block:
            return block
    idx = text.find("def run(")
    if idx != -1:
        tail = text[idx:]
        stop = tail.find("```")
        return (tail[:stop] if stop != -1 else tail).strip()
    return None
