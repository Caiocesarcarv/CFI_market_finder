"""Análises textuais com IA (Fase 4): análise por país e relatório executivo.

Fluxo de cada geração:
1. Os dados vêm do motor de análise (markets.py) — reais + pontuação CFI.
2. Montamos uma FICHA DE DADOS compacta, com números já formatados em pt-BR.
3. A IA (Groq) devolve JSON estruturado seguindo prompts.py.
4. O conteúdo é saneado (tipos, tamanhos, valores permitidos) e todos os
   números em US$ e % do texto são CONFERIDOS contra a ficha
   (verify_numbers). Divergências são devolvidas em `verification`.
5. O resultado fica em cache (api_cache) e é exportável em Markdown.

Todo texto gerado é rotulado como ESTIMATIVA.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.errors import AppError
from app.models import DataNature
from app.services import cache, groq_client, markets, prompts
from app.services.classification import classify_code
from app.services.http import ExternalServiceError
from app.services.analysis import GROWTH_JUMP_PCT
from app.services.reference import get_ncm

CACHE_TTL = timedelta(days=7)
DISCLAIMER = ("Texto gerado por inteligência artificial a partir dos indicadores da plataforma. "
              "É uma estimativa para apoiar a decisão: confirme tarifas, exigências sanitárias e "
              "técnicas, acordos comerciais e condições logísticas antes de agir.")
PRIORITIES = ("alta", "media", "baixa")
TERMS = ("curto", "medio", "longo")


# ====================================================================== formatação

def usd(v) -> str:
    if v is None:
        return "n/d"
    v = float(v)
    if abs(v) >= 1e9:
        s, unit = f"{v / 1e9:.1f}", "bi"
    elif abs(v) >= 1e6:
        s, unit = f"{v / 1e6:.1f}", "mi"
    elif abs(v) >= 1e3:
        s, unit = f"{v / 1e3:.0f}", "mil"
    else:
        return f"US$ {v:.0f}"
    return f"US$ {s.replace('.', ',')} {unit}"


def pct(v, signed: bool = False) -> str:
    if v is None:
        return "n/d"
    s = f"{float(v):+.1f}" if signed else f"{float(v):.1f}"
    return s.replace(".", ",") + "%"


def num(v, nd: int = 1) -> str:
    return "n/d" if v is None else f"{float(v):.{nd}f}".replace(".", ",")


def _product_label(db: sqlite3.Connection, raw_code: str, product: str | None) -> str:
    code = classify_code(raw_code)
    official = get_ncm(db, code.code_digits) if code.code_type == "NCM" else None
    parts = [p for p in [product, official and official["description"]] if p]
    label = " — ".join(dict.fromkeys(parts)) or f"produto do código {code.code_type} {code.code_digits}"
    return f"{label} ({code.code_type} {code.code_digits}; dados internacionais no HS {code.hs_code})"


# ====================================================================== fichas de dados

def _supplier_line(suppliers: list[dict], limit: int = 6) -> str:
    return "; ".join(
        f"{s.get('country_pt') or s['country']} {pct(s['share_pct'])} ({usd(s['value_usd'])})" for s in suppliers[:limit]
    ) or "sem detalhamento disponível"


def _growth_text(i: dict) -> str | None:
    """Crescimento em % a.a.; sobre base muito pequena, descreve o salto em valores
    (uma taxa de milhares de % ao ano é correta, mas não informa nada)."""
    if i["cagr_pct"] is None:
        return None
    if i["cagr_pct"] >= GROWTH_JUMP_PCT and i.get("cagr_base_value_usd"):
        first = i["cagr_period"].split("–")[0]
        return (f"mercado em formação: importações saltaram de {usd(i['cagr_base_value_usd'])} ({first}) "
                f"para {usd(i['imports_usd'])}")
    return f"crescimento {pct(i['cagr_pct'])} a.a. ({i['cagr_period']})"


def _market_line(m: dict) -> str:
    i = m["indicators"]
    parts = [
        f"pontuação {num(m['score'])}",
        f"importações {usd(i['imports_usd'])} ({pct(i['world_share_pct'])} do mundo)",
    ]
    growth = _growth_text(i)
    if growth:
        parts.append(growth)
    if (i["brazil_share_pct"] or 0) > 0:
        rank = f", {i['brazil_supplier_rank']}º fornecedor" if i["brazil_supplier_rank"] else ""
        parts.append(f"Brasil fornece {pct(i['brazil_share_pct'])} das importações do país{rank}")
    else:
        parts.append("Brasil não fornece")
    lead = i.get("leader_supplier")
    if lead and lead.get("iso3") != "BRA":
        parts.append(f"líder: {lead['country']} {pct(lead['share_pct'])}")
    if i.get("brazil_exports_fob_usd"):
        parts.append(f"Comex Stat: {usd(i['brazil_exports_fob_usd'])} FOB")
    return f"{m.get('country_pt') or m['country']} ({m['iso3']}) — " + " | ".join(parts)


def country_context(detail: dict, product_label: str) -> str:
    m, i, ref = detail["market"], detail["market"]["indicators"], detail["reference_year"]
    name = m.get("country_pt") or m["country"]
    incomplete = set(detail.get("incomplete_years") or [])
    history = "; ".join(
        f"{h['year']}: {usd(h['value_usd'])}" + (" (ano incompleto na base)" if h["year"] in incomplete else "")
        for h in detail["history"] if h["value_usd"] is not None
    )
    lines = [
        "FICHA DE DADOS",
        f"Produto: {product_label}",
        f"Ano de referência: {ref}. Fontes: UN Comtrade (importações declaradas pelos países, geralmente CIF) "
        "e Comex Stat (exportações brasileiras, FOB).",
        f"Participação mundial do Brasil (média de referência): {pct(detail['brazil_world_share_pct'])} das "
        "importações mundiais deste produto.",
        "",
        f"MERCADO: {name} ({m['iso3']})",
        f"- Ranking CFI: {m['rank']}º de {detail['rank_among']} mercados avaliados; pontuação de atratividade "
        f"{num(m['score'])}/100 (estimativa).",
        f"- Importações em {ref}: {usd(i['imports_usd'])} ({pct(i['world_share_pct'])} das importações mundiais).",
        f"- Série de importações: {history or 'n/d'}.",
    ]
    if i["cagr_pct"] is not None:
        if i["cagr_pct"] >= GROWTH_JUMP_PCT:
            lines.append(f"- Evolução {i['cagr_period']}: {_growth_text(i)} (base inicial muito pequena; "
                         "não use taxa percentual de crescimento).")
        else:
            lines.append(f"- Crescimento médio anual {i['cagr_period']}: {pct(i['cagr_pct'])}.")
    if i["yoy_pct"] is not None:
        lines.append(f"- Variação em {ref} frente ao ano anterior: {pct(i['yoy_pct'], signed=True)}.")
    if (i["brazil_share_pct"] or 0) > 0:
        rank = f"; {i['brazil_supplier_rank']}º maior fornecedor" if i["brazil_supplier_rank"] else ""
        lines.append(f"- Brasil neste mercado: {pct(i['brazil_share_pct'])} das importações "
                     f"({usd(i['imports_from_brazil_usd'])}){rank}.")
    else:
        lines.append("- Brasil neste mercado: o país não registra importações do Brasil neste produto.")
    if i["brazil_gap_pp"] is not None:
        lines.append(f"- Diferença para a média mundial do Brasil: {num(i['brazil_gap_pp'])} pontos percentuais.")
    if i.get("brazil_exports_fob_usd"):
        lines.append(f"- Exportações brasileiras registradas no Comex Stat em {ref}: {usd(i['brazil_exports_fob_usd'])} FOB.")
    lines.append(f"- Principais fornecedores em {ref}: {_supplier_line(detail['suppliers'])}.")
    if i.get("hhi_competitors") is not None:
        lines.append(f"- HHI dos concorrentes do Brasil: {num(i['hhi_competitors'], 2)}.")
    comps = "; ".join(f"{c['label']} {num(c['score'], 0)} de 100" for c in m["components"] if c["score"] is not None)
    lines.append(f"- Percentis dos componentes da pontuação: {comps}.")
    if m["highlights"]:
        lines.append(f"- Destaques calculados: {'; '.join(m['highlights'])}.")
    if detail["warnings"]:
        lines += ["", "LIMITAÇÕES DOS DADOS:"] + [f"- {w}" for w in detail["warnings"]]
    lines += ["", prompts.READING_GUIDE]
    return "\n".join(lines)


def report_markets(ranking: dict, top: int) -> tuple[list[dict], list[dict]]:
    """Mercados enviados à IA: os `top` por pontuação + os maiores importadores fora dessa lista."""
    by_score = ranking["markets"][:top]
    chosen = {m["iso3"] for m in by_score}
    largest = sorted(ranking["markets"], key=lambda m: m["indicators"]["imports_usd"] or 0, reverse=True)
    big_outside = [m for m in largest[:5] if m["iso3"] not in chosen]
    return by_score, big_outside


def report_context(ranking: dict, product_label: str, top: int) -> str:
    b, g, ref = ranking["benchmark"], ranking["global_suppliers"], ranking["reference_year"]
    by_score, big_outside = report_markets(ranking, top)
    exporters = "; ".join(f"{s.get('country_pt') or s['country']} {pct(s['share_pct'])}" for s in g["top"][:6])
    br = g.get("brazil")
    lines = [
        "FICHA DE DADOS",
        f"Produto: {product_label}",
        f"Ano de referência: {ref}. Fontes: UN Comtrade (importações declaradas, geralmente CIF) e "
        "Comex Stat (exportações brasileiras, FOB).",
        "",
        "MUNDO",
        f"- Importações mundiais em {ref}: {usd(b['world_imports_usd'])}"
        + (f"; variação comparável frente ao ano anterior: {pct(b['world_yoy_comparable_pct'], signed=True)}"
           if b.get("world_yoy_comparable_pct") is not None else "") + ".",
        f"- Principais exportadores (segundo os importadores): {exporters or 'n/d'}.",
        f"- Brasil: {br['rank']}º exportador, com {pct(b['brazil_world_share_pct'])} das importações mundiais."
        if br else "- Brasil: não aparece entre os exportadores deste produto.",
        f"- Mercados avaliados: {b['markets_evaluated']} (excluídos {b['markets_excluded_small']} muito pequenos).",
        "",
        "METODOLOGIA DA PONTUAÇÃO CFI (estimativa): "
        + "; ".join(f"{ranking['methodology']['indicators'][k]['label']} {round(w * 100)}%"
                    for k, w in ranking["methodology"]["weights"].items()) + ".",
        "",
        f"MERCADOS AVALIADOS — {len(by_score)} melhores por pontuação:",
    ]
    lines += [f"{m['rank']}. {_market_line(m)}" for m in by_score]
    if big_outside:
        lines += ["", "MERCADOS AVALIADOS — maiores importadores fora da lista acima:"]
        lines += [f"{m['rank']}. {_market_line(m)}" for m in big_outside]
    if ranking["warnings"]:
        lines += ["", "LIMITAÇÕES DOS DADOS:"] + [f"- {w}" for w in ranking["warnings"]]
    lines += ["", prompts.READING_GUIDE]
    return "\n".join(lines)


# ====================================================================== checagem de números

_MONEY = re.compile(r"US\$\s*([\d][\d.,]*)\s*(bilh(?:ão|ões|oes|ao)|bi|milh(?:ão|ões|oes|ao)|mi|mil)?", re.I)
_PCT = re.compile(r"([+\-−]?\d[\d.,]*)\s*(%|p\.\s?p\.|pontos percentuais)", re.I)
_SCALE = {"bi": 1e9, "bilh": 1e9, "mi": 1e6, "milh": 1e6, "mil": 1e3}


def _to_float(s: str) -> float | None:
    s = s.strip().rstrip(".,").replace("−", "-")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) == 3:
        s = s.replace(".", "")  # 1.234 = milhar
    elif s.count(".") > 1:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _extract(text: str) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    money, pcts = [], []
    for m in _MONEY.finditer(text):
        v = _to_float(m.group(1))
        if v is None:
            continue
        unit = (m.group(2) or "").lower()
        scale = next((s for k, s in _SCALE.items() if unit.startswith(k)), 1)
        money.append((m.group(0).strip(), v * scale))
    for m in _PCT.finditer(text):
        v = _to_float(m.group(1))
        if v is not None:
            pcts.append((m.group(0).strip(), abs(v)))
    return money, pcts


def verify_numbers(texts: list[str], context: str) -> dict:
    """Confere se cada valor em US$ e % citado pela IA existe na ficha de dados.

    Tolerância para arredondamento: 6% relativo em valores monetários;
    0,6 ponto (ou 3%) em percentuais.
    """
    allowed_money, allowed_pct = _extract(context)
    money_vals = [v for _, v in allowed_money]
    pct_vals = [v for _, v in allowed_pct]
    checked, unverified = 0, []
    for text in texts:
        money, pcts = _extract(text)
        for raw, v in money:
            checked += 1
            if not any(abs(v - a) <= 0.06 * max(abs(a), 1) for a in money_vals):
                unverified.append(raw)
        for raw, v in pcts:
            checked += 1
            if not any(abs(v - a) <= max(0.6, 0.03 * a) for a in pct_vals):
                unverified.append(raw)
    unique = list(dict.fromkeys(unverified))
    return {"numbers_checked": checked, "unverified": unique, "ok": not unique}


# ====================================================================== saneamento

def _s(v, limit: int = 1500) -> str:
    return re.sub(r"\s+", " ", str(v or "")).strip()[:limit]


def _ls(v, max_items: int = 6, limit: int = 600) -> list[str]:
    if not isinstance(v, list):
        return []
    return [_s(x, limit) for x in v if _s(x)][:max_items]


def _choice(v, options: tuple[str, ...], default: str) -> str:
    v = _s(v).lower().replace("é", "e")
    return v if v in options else default


def _recs(v, with_term: bool = False, max_items: int = 6) -> list[dict]:
    out = []
    for r in v if isinstance(v, list) else []:
        if not isinstance(r, dict) or not _s(r.get("acao")):
            continue
        item = {"acao": _s(r.get("acao"), 300), "prioridade": _choice(r.get("prioridade"), PRIORITIES, "media"),
                "justificativa": _s(r.get("justificativa"), 600)}
        if with_term:
            item["prazo"] = _choice(r.get("prazo"), TERMS, "medio")
        out.append(item)
    return out[:max_items]


def _all_texts(content: dict) -> list[str]:
    out = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, list):
            for y in x:
                walk(y)
        elif isinstance(x, dict):
            for k, y in x.items():
                if k not in ("iso3", "prioridade", "prazo"):
                    walk(y)
    walk(content)
    return out


# ====================================================================== geração

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def country_analysis(
    db: sqlite3.Connection, settings: Settings, raw_code: str, iso3: str,
    product: str | None = None, refresh: bool = False,
) -> dict:
    detail = markets.build_market_detail(db, settings, raw_code, iso3)
    label = _product_label(db, raw_code, product)
    key = "|".join([settings.groq_model, "country", detail["code"], detail["market"]["iso3"],
                    str(detail["reference_year"]), str(detail["fetched_at"]), label])
    if not refresh:
        hit = cache.get_cached_payload(db, "ai_country", key)
        if hit:
            return {**hit["payload"], "from_cache": True}

    context = country_context(detail, label)
    raw = groq_client.chat_json(settings, prompts.BASE_RULES + "\n\n" + prompts.COUNTRY_TASK, context,
                                temperature=0.2, max_tokens=3500, reasoning_effort="medium")
    content = {
        "resumo": _s(raw.get("resumo"), 800),
        "oportunidades": _ls(raw.get("oportunidades")),
        "riscos": _ls(raw.get("riscos")),
        "concorrencia": _s(raw.get("concorrencia"), 1200),
        "estrategia_entrada": _ls(raw.get("estrategia_entrada")),
        "recomendacoes": _recs(raw.get("recomendacoes")),
        "pontos_a_verificar": _ls(raw.get("pontos_a_verificar"), 8),
    }
    if not content["resumo"]:
        raise ExternalServiceError("Groq", "a IA devolveu uma análise vazia; tente novamente")

    m = detail["market"]
    result = {
        "data_nature": DataNature.ESTIMATIVA.value,
        "source": f"Texto gerado por IA (Groq, {settings.groq_model}) a partir de indicadores CFI "
                  f"({detail['source'].replace('Cálculo CFI sobre ', '')})",
        "model": settings.groq_model,
        "generated_at": _now(),
        "code": detail["code"], "code_type": detail["code_type"], "hs_code": detail["hs_code"],
        "product": label,
        "reference_year": detail["reference_year"],
        "market": {"iso3": m["iso3"], "country": m.get("country_pt") or m["country"], "rank": m["rank"],
                   "rank_among": detail["rank_among"], "score": m["score"], "indicators": m["indicators"]},
        "content": content,
        "verification": verify_numbers(_all_texts(content), context),
        "warnings": detail["warnings"],
        "disclaimer": DISCLAIMER,
        "data_context": context,
    }
    result["markdown"] = country_markdown(result)
    cache.set_cached_payload(db, "ai_country", key, result, DataNature.ESTIMATIVA.value, CACHE_TTL)
    return {**result, "from_cache": False}


def executive_report(
    db: sqlite3.Connection, settings: Settings, raw_code: str,
    product: str | None = None, top: int = 8, refresh: bool = False,
) -> dict:
    ranking = markets.build_ranking(db, settings, raw_code, top=250)
    if not ranking["markets"]:
        raise AppError(404, "Não há mercados avaliados para este código; não é possível gerar o relatório.")
    label = _product_label(db, raw_code, product)
    key = "|".join([settings.groq_model, "report", ranking["code"], str(top),
                    str(ranking["reference_year"]), str(ranking["fetched_at"]), label])
    if not refresh:
        hit = cache.get_cached_payload(db, "ai_report", key)
        if hit:
            return {**hit["payload"], "from_cache": True}

    context = report_context(ranking, label, top)
    raw = groq_client.chat_json(settings, prompts.BASE_RULES + "\n\n" + prompts.REPORT_TASK, context,
                                temperature=0.2, max_tokens=4500, reasoning_effort="medium")

    by_score, big_outside = report_markets(ranking, top)
    eligible = {m["iso3"]: m for m in by_score + big_outside}
    priorities, rejected = [], []
    for p in raw.get("mercados_prioritarios") or []:
        if not isinstance(p, dict):
            continue
        iso = _s(p.get("iso3")).upper()[:3]
        if iso not in eligible:
            rejected.append(iso or "?")
            continue
        if any(x["iso3"] == iso for x in priorities):
            continue
        m = eligible[iso]
        priorities.append({
            "iso3": iso, "pais": m.get("country_pt") or m["country"], "rank": m["rank"], "score": m["score"],
            "justificativa": _s(p.get("justificativa"), 800), "estrategia": _s(p.get("estrategia"), 800),
        })
    content = {
        "titulo": _s(raw.get("titulo"), 160) or "Relatório de oportunidades de exportação",
        "sumario_executivo": _s(raw.get("sumario_executivo"), 2000),
        "panorama_mundial": _s(raw.get("panorama_mundial"), 1500),
        "mercados_prioritarios": priorities[:5],
        "recomendacoes": _recs(raw.get("recomendacoes"), with_term=True),
        "riscos_e_limitacoes": _ls(raw.get("riscos_e_limitacoes")),
        "proximos_passos": _ls(raw.get("proximos_passos"), 8),
    }
    if not content["sumario_executivo"]:
        raise ExternalServiceError("Groq", "a IA devolveu um relatório vazio; tente novamente")

    verification = verify_numbers(_all_texts(content), context)
    if rejected:
        verification["rejected_markets"] = rejected
        verification["ok"] = False

    result = {
        "data_nature": DataNature.ESTIMATIVA.value,
        "source": f"Texto gerado por IA (Groq, {settings.groq_model}) a partir de indicadores CFI "
                  f"({ranking['source'].replace('Cálculo CFI sobre ', '')})",
        "model": settings.groq_model,
        "generated_at": _now(),
        "code": ranking["code"], "code_type": ranking["code_type"], "hs_code": ranking["hs_code"],
        "product": label,
        "reference_year": ranking["reference_year"],
        "benchmark": ranking["benchmark"],
        "global_suppliers": ranking["global_suppliers"],
        "methodology": ranking["methodology"],
        "markets_table": [
            {"rank": m["rank"], "iso3": m["iso3"], "country": m.get("country_pt") or m["country"],
             "score": m["score"], **{k: m["indicators"][k] for k in
                                     ("imports_usd", "world_share_pct", "cagr_pct", "brazil_share_pct")}}
            for m in by_score
        ],
        "content": content,
        "verification": verification,
        "warnings": ranking["warnings"],
        "disclaimer": DISCLAIMER,
        "data_context": context,
    }
    result["markdown"] = report_markdown(result)
    cache.set_cached_payload(db, "ai_report", key, result, DataNature.ESTIMATIVA.value, CACHE_TTL)
    return {**result, "from_cache": False}


# ====================================================================== Markdown

_PRIO = {"alta": "Alta", "media": "Média", "baixa": "Baixa"}
_TERM = {"curto": "Curto prazo", "medio": "Médio prazo", "longo": "Longo prazo"}


def _bullets(items: list[str]) -> list[str]:
    return [f"- {x}" for x in items] or ["- (não informado)"]


def _verification_md(v: dict) -> list[str]:
    if v["ok"]:
        return [f"Conferência automática: os {v['numbers_checked']} valores numéricos citados pela IA "
                "conferem com os dados da plataforma."]
    lines = []
    if v["unverified"]:
        lines.append("**Atenção:** a IA citou valores que não constam nos dados da plataforma e devem ser "
                     f"desconsiderados: {', '.join(v['unverified'])}.")
    if v.get("rejected_markets"):
        lines.append(f"Mercados sugeridos fora da lista avaliada foram descartados: {', '.join(v['rejected_markets'])}.")
    return lines


def _date(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").strftime("%d/%m/%Y %H:%M UTC")


def country_markdown(r: dict) -> str:
    c, m, i = r["content"], r["market"], r["market"]["indicators"]
    md = [
        f"# {m['country']} — análise de mercado",
        "",
        f"**Produto:** {r['product']}  ",
        f"**Ano de referência:** {r['reference_year']} · **Posição CFI:** {m['rank']}º de {m['rank_among']} "
        f"· **Pontuação:** {num(m['score'])}/100 *(estimativa)*  ",
        f"*Gerado em {_date(r['generated_at'])} por IA ({r['model']}) — natureza: estimativa.*",
        "",
        "## Indicadores (dados reais)",
        "",
        "| Indicador | Valor |",
        "|---|---|",
        f"| Importações {r['reference_year']} | {usd(i['imports_usd'])} ({pct(i['world_share_pct'])} do mundo) |",
        f"| Crescimento médio anual | {pct(i['cagr_pct'])} ({i['cagr_period'] or 'n/d'}) |",
        f"| Participação do Brasil | {pct(i['brazil_share_pct'])} |",
        f"| Posição do Brasil entre fornecedores | {str(i['brazil_supplier_rank']) + 'º' if i['brazil_supplier_rank'] else 'não fornece'} |",
        f"| Exportações brasileiras (Comex Stat, FOB) | {usd(i['brazil_exports_fob_usd'])} |",
        "",
        "## Resumo", "", c["resumo"], "",
        "## Oportunidades", "", *_bullets(c["oportunidades"]), "",
        "## Riscos", "", *_bullets(c["riscos"]), "",
        "## Concorrência", "", c["concorrencia"] or "(não informado)", "",
        "## Estratégia de entrada", "", *_bullets(c["estrategia_entrada"]), "",
        "## Recomendações", "",
        *[f"- **{_PRIO[x['prioridade']]}** — {x['acao']}. {x['justificativa']}" for x in c["recomendacoes"]], "",
        "## Pontos a verificar (fora dos dados)", "", *_bullets(c["pontos_a_verificar"]), "",
        "---", "",
        f"*Fontes: {r['source']}.*  ",
        *[f"*{line}*" for line in _verification_md(r["verification"])],
        *[f"*Limitação: {w}*  " for w in r["warnings"]],
        "", f"*{r['disclaimer']}*",
    ]
    return "\n".join(md)


def report_markdown(r: dict) -> str:
    c, b = r["content"], r["benchmark"]
    md = [
        f"# {c['titulo']}",
        "",
        f"**Produto:** {r['product']}  ",
        f"**Ano de referência:** {r['reference_year']} · **Importações mundiais:** {usd(b['world_imports_usd'])} "
        f"· **Participação do Brasil:** {pct(b['brazil_world_share_pct'])}  ",
        f"*Gerado em {_date(r['generated_at'])} por IA ({r['model']}) — natureza: estimativa.*",
        "",
        "## Sumário executivo", "", c["sumario_executivo"], "",
        "## Panorama mundial", "", c["panorama_mundial"] or "(não informado)", "",
        "## Ranking de mercados (dados da plataforma)", "",
        "| # | Mercado | Pontuação | Importações | % mundo | Cresc. a.a. | % Brasil |",
        "|---|---|---|---|---|---|---|",
        *[f"| {m['rank']} | {m['country']} | {num(m['score'])} | {usd(m['imports_usd'])} | {pct(m['world_share_pct'])} "
          f"| {'salto*' if (m['cagr_pct'] or 0) >= GROWTH_JUMP_PCT else pct(m['cagr_pct'])} "
          f"| {pct(m['brazil_share_pct'])} |" for m in r["markets_table"]],
        *(["", "*\\*Salto: importações partiram de base muito pequena; a taxa anual não é representativa.*"]
          if any((m["cagr_pct"] or 0) >= GROWTH_JUMP_PCT for m in r["markets_table"]) else []),
        "",
        "## Mercados prioritários", "",
    ]
    for p in c["mercados_prioritarios"]:
        md += [f"### {p['pais']} (posição {p['rank']}, pontuação {num(p['score'])})", "",
               f"**Por quê:** {p['justificativa']}", "", f"**Como abordar:** {p['estrategia']}", ""]
    md += [
        "## Recomendações", "",
        *[f"- **{_PRIO[x['prioridade']]} · {_TERM[x['prazo']]}** — {x['acao']}. {x['justificativa']}"
          for x in c["recomendacoes"]], "",
        "## Riscos e limitações", "", *_bullets(c["riscos_e_limitacoes"]), "",
        "## Próximos passos", "", *_bullets(c["proximos_passos"]), "",
        "## Metodologia e fontes", "",
        "Pontuação de atratividade (estimativa CFI): "
        + "; ".join(f"{r['methodology']['indicators'][k]['label']} {round(w * 100)}%"
                    for k, w in r["methodology"]["weights"].items()) + ".  ",
        r["methodology"]["values"] + "  ",
        f"Fontes: {r['source']}.",
        "",
        *_verification_md(r["verification"]),
        *[f"- Limitação: {w}" for w in r["warnings"]],
        "", "---", "", f"*{r['disclaimer']}*",
    ]
    return "\n".join(md)
