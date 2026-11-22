"""Cliente mínimo da API Groq (compatível com o formato OpenAI).

Observação: no plano gratuito o Groq limita tokens por minuto (ex.: 8.000 no
gpt-oss-120b, somando pergunta e resposta). Por isso os contextos enviados
são compactos e as respostas têm limite de tamanho; tudo é guardado em cache.
"""

from __future__ import annotations

import json

from app.config import Settings
from app.services.http import ExternalServiceError, request_json

SOURCE = "Groq"
API_URL = "https://api.groq.com/openai/v1/chat/completions"


def chat_json(
    settings: Settings,
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
    reasoning_effort: str = "medium",
) -> dict:
    """Envia uma conversa e devolve a resposta do modelo já convertida de JSON."""
    if not settings.groq_configured:
        raise ExternalServiceError(SOURCE, "chave de API não configurada (GROQ_API_KEY no .env)", 503)

    body = {
        "model": settings.groq_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
        "temperature": temperature,
    }
    if max_tokens:
        body["max_completion_tokens"] = max_tokens
    if settings.groq_model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = reasoning_effort

    try:
        resp = request_json("POST", API_URL, source=SOURCE, json=body,
                            headers={"Authorization": f"Bearer {settings.groq_api_key}"}, timeout=120, retries=1)
    except ExternalServiceError as exc:
        msg = exc.message.lower()
        if "does not exist" in msg or "model_not_found" in msg:
            raise ExternalServiceError(
                SOURCE, f"o modelo '{settings.groq_model}' não está disponível; altere GROQ_MODEL no .env", 502
            ) from exc
        if exc.status_code == 429:
            raise ExternalServiceError(
                SOURCE, "limite de uso por minuto do Groq atingido (plano gratuito); aguarde cerca de 1 minuto "
                        "e tente novamente", 429,
            ) from exc
        if "too large" in msg or "tokens per minute" in msg or "rate limit" in msg:
            raise ExternalServiceError(
                SOURCE, "a solicitação excede o limite de tokens por minuto do Groq; aguarde 1 minuto "
                        "ou reduza a quantidade de mercados", 429,
            ) from exc
        raise

    try:
        choice = resp["choices"][0]
        if choice.get("finish_reason") == "length":
            raise ExternalServiceError(SOURCE, "a resposta da IA foi interrompida por limite de tamanho; tente novamente")
        return json.loads(choice["message"]["content"])
    except ExternalServiceError:
        raise
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ExternalServiceError(SOURCE, "o modelo não devolveu um JSON válido") from exc
