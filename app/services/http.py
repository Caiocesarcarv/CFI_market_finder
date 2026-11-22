"""Cliente HTTP comum às integrações externas.

Converte falhas de rede e respostas de erro em ExternalServiceError, com
mensagens em português, e faz novas tentativas em erros temporários
(timeout, queda de conexão, HTTP 429/5xx).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger("cfi.http")

_session = requests.Session()
_session.headers.update({"User-Agent": "CFI-Market-Finder/1.0", "Accept": "application/json"})


class ExternalServiceError(Exception):
    """Falha ao obter dados de um serviço externo.

    status_code é o código HTTP que a NOSSA API devolverá ao frontend:
    503 (indisponível), 429 (limite de uso), 502 (resposta inválida/erro do provedor).
    """

    def __init__(self, source: str, message: str, status_code: int = 502):
        super().__init__(f"{source}: {message}")
        self.source = source
        self.message = message
        self.status_code = status_code


def request_json(
    method: str,
    url: str,
    *,
    source: str,
    params: dict | None = None,
    json: Any = None,
    headers: dict | None = None,
    timeout: float = 60,
    retries: int = 2,
) -> Any:
    """Executa a requisição e devolve o JSON, com novas tentativas em erros temporários."""
    last_error = "erro desconhecido"
    for attempt in range(retries + 1):
        if attempt:
            time.sleep(min(2 ** attempt, 8))
        try:
            resp = _session.request(method, url, params=params, json=json, headers=headers, timeout=timeout)
        except requests.Timeout:
            last_error = "o serviço demorou demais para responder"
            continue
        except requests.exceptions.SSLError:
            raise ExternalServiceError(source, "falha no certificado de segurança (HTTPS) do servidor", 502)
        except requests.ConnectionError:
            last_error = "sem conexão com o servidor (verifique a internet)"
            continue

        if resp.status_code == 429:
            last_error = "limite de requisições atingido; tente novamente mais tarde"
            if attempt < retries:
                retry_after = resp.headers.get("Retry-After", "")
                if retry_after.isdigit() and int(retry_after) <= 10:
                    time.sleep(int(retry_after))
                continue
            raise ExternalServiceError(source, last_error, 429)
        if resp.status_code in (401, 403):
            raise ExternalServiceError(source, "chave de API inválida ou sem permissão (verifique o .env)", 502)
        if resp.status_code >= 500:
            last_error = f"serviço indisponível (HTTP {resp.status_code})"
            continue
        if resp.status_code >= 400:
            logger.warning("%s HTTP %s: %s", source, resp.status_code, resp.text[:500])
            raise ExternalServiceError(source, _provider_message(resp), 502)

        try:
            return resp.json()
        except ValueError:
            raise ExternalServiceError(source, "resposta em formato inesperado (não é JSON)", 502)

    raise ExternalServiceError(source, last_error, 503)


def _provider_message(resp: requests.Response) -> str:
    """Extrai a mensagem de erro do corpo da resposta, quando houver."""
    try:
        body = resp.json()
    except ValueError:
        return f"requisição recusada (HTTP {resp.status_code})"
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict) and err.get("message"):
        return str(err["message"])
    if isinstance(err, str) and err:
        return err
    if isinstance(body, dict) and body.get("message"):
        return str(body["message"])
    return f"requisição recusada (HTTP {resp.status_code})"
