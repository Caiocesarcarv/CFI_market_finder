"""Cliente mínimo da API Groq (compatível com o formato OpenAI)."""

from __future__ import annotations

import json

from app.config import Settings
from app.services.http import ExternalServiceError, request_json

SOURCE = "Groq"
API_URL = "https://api.groq.com/openai/v1/chat/completions"


def chat_json(settings: Settings, system: str, user: str, temperature: float = 0.1) -> dict:
    """Envia uma conversa e devolve a resposta do modelo já convertida de JSON."""
    if not settings.groq_configured:
        raise ExternalServiceError(SOURCE, "chave de API não configurada (GROQ_API_KEY no .env)", 503)

    body = {
        "model": settings.groq_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    if settings.groq_model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "medium"

    try:
        resp = request_json("POST", API_URL, source=SOURCE, json=body,
                            headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=60)
    except ExternalServiceError as exc:
        if "does not exist" in exc.message or "model_not_found" in exc.message:
            raise ExternalServiceError(
                SOURCE, f"o modelo '{settings.groq_model}' não está disponível; altere GROQ_MODEL no .env", 502
            ) from exc
        raise

    try:
        content = resp["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ExternalServiceError(SOURCE, "o modelo não devolveu um JSON válido") from exc
