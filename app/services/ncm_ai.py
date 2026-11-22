"""Interpretação do nome do produto → código NCM/HS com IA (Groq).

Fluxo:
1. Busca textual na tabela oficial NCM (candidatos locais).
2. A IA recebe a descrição do usuário + candidatos e escolhe até 3 NCMs,
   podendo propor códigos fora da lista quando nenhum servir.
3. TODA sugestão é conferida na tabela oficial: códigos inexistentes são
   descartados, e a descrição exibida é sempre a oficial (não a da IA).

O resultado é uma ESTIMATIVA: a classificação fiscal definitiva deve ser
confirmada por um profissional (despachante/classificador).
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata
from datetime import timedelta

from app.config import Settings
from app.models import DataNature
from app.services import cache, groq_client
from app.services.http import ExternalServiceError
from app.services.reference import get_ncm, is_ready, search_ncm

CACHE_TTL = timedelta(days=30)
MAX_SUGGESTIONS = 3

SYSTEM_PROMPT = """Você é especialista em classificação fiscal de mercadorias na NCM (Nomenclatura \
Comum do Mercosul), baseada no Sistema Harmonizado (SH), aplicando as Regras Gerais de Interpretação.

Tarefa: dado o produto descrito pelo usuário, indique as NCMs (8 dígitos) mais prováveis.

Regras:
- Prefira códigos da lista de candidatos fornecida (extraída da tabela oficial).
- Se nenhum candidato servir, você pode propor outra NCM que tenha certeza de que existe.
- Atenção ao estado do produto (in natura, torrado, congelado, processado, em grão, moído etc.).
- Se a descrição for ambígua, devolva alternativas e explique o que diferencia cada uma.
- Não invente códigos. Responda somente com JSON no formato:
{"interpretacao": "como você entendeu o produto (1 frase)",
 "sugestoes": [{"ncm": "8 dígitos", "confianca": "alta|media|baixa", "justificativa": "1-2 frases"}],
 "observacao": "dúvida ou informação adicional útil, ou string vazia"}
No máximo 3 sugestões, da mais para a menos provável."""


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def suggest_codes(conn: sqlite3.Connection, settings: Settings, description: str, refresh: bool = False) -> dict:
    description = description.strip()
    if not is_ready(conn):
        raise ExternalServiceError(
            "Tabela NCM", "a tabela oficial NCM ainda está sendo baixada; tente novamente em instantes", 503
        )

    cache_key = f"{settings.groq_model}|{_normalize(description)}"
    if not refresh:
        hit = cache.get_cached_payload(conn, "groq_ncm", cache_key)
        if hit:
            return {**hit["payload"], "from_cache": True}

    candidates = search_ncm(conn, description, limit=30)
    lines = "\n".join(f"{c['co_ncm']} - {c['description']}" for c in candidates) or "(nenhum candidato encontrado)"
    user_msg = f"Produto: {description}\n\nCandidatos da tabela oficial NCM:\n{lines}"

    answer = groq_client.chat_json(settings, SYSTEM_PROMPT, user_msg)

    suggestions, discarded, seen = [], [], set()
    for s in (answer.get("sugestoes") or [])[: MAX_SUGGESTIONS + 2]:
        code = re.sub(r"\D", "", str(s.get("ncm", "")))
        if code in seen:
            continue
        seen.add(code)
        official = get_ncm(conn, code) if len(code) == 8 else None
        if official is None:
            discarded.append({"ncm": s.get("ncm"), "motivo": "código não existe na tabela oficial NCM"})
            continue
        suggestions.append({
            "ncm": code,
            "hs6": code[:6],
            "official_description": official["description"],
            "unit": official["unit"],
            "confidence": s.get("confianca") if s.get("confianca") in ("alta", "media", "baixa") else "baixa",
            "justification": str(s.get("justificativa") or "")[:600],
            "in_local_candidates": any(c["co_ncm"] == code for c in candidates),
        })
        if len(suggestions) == MAX_SUGGESTIONS:
            break

    result = {
        "query": description,
        "data_nature": DataNature.ESTIMATIVA.value,
        "source": f"Groq ({settings.groq_model}) + tabela oficial NCM (Comex Stat)",
        "interpretation": str(answer.get("interpretacao") or "")[:400],
        "observation": str(answer.get("observacao") or "")[:600],
        "suggestions": suggestions,
        "discarded": discarded,
        "local_matches": candidates[:10],
        "disclaimer": "Sugestão gerada por IA e conferida na tabela oficial NCM. "
                      "A classificação fiscal definitiva deve ser confirmada por um profissional.",
    }
    if suggestions:  # só guarda em cache respostas úteis
        cache.set_cached_payload(conn, "groq_ncm", cache_key, result, DataNature.ESTIMATIVA.value, CACHE_TTL)
    return {**result, "from_cache": False}
