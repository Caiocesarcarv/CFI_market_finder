"""Motor de análise de mercados (Fase 3).

A partir dos dados REAIS da UN Comtrade (e, quando disponível, do Comex Stat),
calcula indicadores por país importador e uma pontuação de atratividade.

Indicadores (todos derivados de dados reais):
- Tamanho do mercado ............ valor importado no ano de referência
- Crescimento ................... CAGR das importações (até 3 anos completos)
- Espaço para o Brasil .......... participação média do Brasil no mundo
                                  menos a participação dele no país
- Abertura a fornecedores ....... 1 − HHI (concentração entre países fornecedores)
- Presença brasileira ........... o Brasil já fornece ao país?

Pontuação (ESTIMATIVA — metodologia da plataforma):
cada indicador é convertido em percentil (0–100) entre os mercados avaliados
e combinado pela média ponderada de WEIGHTS. Indicadores indisponíveis para
um país são ignorados e os pesos restantes são reescalados; o campo
`completeness` mostra quanto do peso total foi efetivamente usado.
"""

from __future__ import annotations

import math

import pandas as pd

from app.services.comtrade import BRAZIL, NON_COUNTRY_PARTNERS, WORLD

WEIGHTS = {
    "market_size": 0.30,
    "growth": 0.25,
    "brazil_room": 0.20,
    "openness": 0.15,
    "brazil_presence": 0.10,
}
LABELS = {
    "market_size": "Tamanho do mercado",
    "growth": "Crescimento das importações",
    "brazil_room": "Espaço para o Brasil",
    "openness": "Abertura a fornecedores",
    "brazil_presence": "Presença brasileira",
}
DESCRIPTIONS = {
    "market_size": "Valor importado pelo país no ano de referência (US$).",
    "growth": "Taxa de crescimento anual composta (CAGR) das importações nos últimos anos completos.",
    "brazil_room": "Participação média do Brasil nas importações mundiais menos a participação dele "
                   "neste país (pontos percentuais). Positivo = Brasil abaixo do seu padrão mundial.",
    "openness": "1 − índice Herfindahl-Hirschman dos fornecedores concorrentes (excluindo o Brasil). "
                "Alto = compras distribuídas entre muitos países; baixo = poucos concorrentes dominam.",
    "brazil_presence": "100 se o Brasil tem ao menos 1% do mercado, 50 se tem menos de 1%, 0 se não fornece.",
}
MAX_GROWTH_SPAN = 3
DEFAULT_MIN_SHARE_PCT = 0.05


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def _r(v, nd=2):
    v = _f(v)
    return None if v is None else round(v, nd)


def _percentile(series: pd.Series) -> pd.Series:
    """Percentil 0–100 (empates recebem a média); NaN permanece NaN."""
    valid = series.dropna()
    if len(valid) <= 1:
        return series.where(series.isna(), 50.0)
    return (series.rank(pct=True, method="average") - 1 / len(valid)) / (1 - 1 / len(valid)) * 100


def cagr(values_by_year: dict[int, float], ref_year: int, complete_years: list[int]) -> tuple[float | None, int | None]:
    """CAGR entre o ano completo mais antigo (até MAX_GROWTH_SPAN anos antes) e ref_year."""
    end = _f(values_by_year.get(ref_year))
    if not end:
        return None, None
    for base in sorted(y for y in complete_years if ref_year - MAX_GROWTH_SPAN <= y < ref_year):
        start = _f(values_by_year.get(base))
        if start and start > 0:
            n = ref_year - base
            return ((end / start) ** (1 / n) - 1) * 100, base
    return None, None


def supplier_table(partners: pd.DataFrame) -> pd.DataFrame:
    """Linhas de fornecedores (exclui parceiros que não são países)."""
    return partners[~partners["partner_code"].isin(NON_COUNTRY_PARTNERS)]


def suppliers_of(partners: pd.DataFrame, reporter_code: int) -> list[dict]:
    """Fornecedores de um país, do maior para o menor, com participação."""
    sup = supplier_table(partners)
    sup = sup[(sup["reporter_code"] == reporter_code) & (sup["value_usd"] > 0)]
    total = sup["value_usd"].sum()
    out = []
    for rank, r in enumerate(sup.sort_values("value_usd", ascending=False).itertuples(index=False), start=1):
        out.append({
            "rank": rank, "partner_code": int(r.partner_code), "iso3": r.partner_iso,
            "country": r.partner_name, "value_usd": _f(r.value_usd),
            "share_pct": _r(r.value_usd / total * 100) if total else None,
        })
    return out


def global_suppliers(partners: pd.DataFrame, limit: int = 10) -> dict:
    """Principais exportadores do produto, pela soma do que os importadores declararam."""
    sup = supplier_table(partners)
    sup = sup[sup["partner_code"] != sup["reporter_code"]]  # remove reimportações
    agg = sup.groupby(["partner_code", "partner_iso", "partner_name"], dropna=False)["value_usd"].sum()
    agg = agg[agg > 0].sort_values(ascending=False)
    total = float(agg.sum())
    rows = [
        {"rank": i, "partner_code": int(k[0]), "iso3": k[1], "country": k[2],
         "value_usd": float(v), "share_pct": _r(v / total * 100) if total else None}
        for i, (k, v) in enumerate(agg.items(), start=1)
    ]
    brazil = next((r for r in rows if r["partner_code"] == BRAZIL), None)
    return {"total_usd": total, "top": rows[:limit], "brazil": brazil, "exporters": len(rows)}


def rank_markets(
    flows: pd.DataFrame,
    partners: pd.DataFrame,
    world_series: list[dict],
    ref_year: int,
    brazil_exports: dict[str, float] | None = None,
    min_share_pct: float = DEFAULT_MIN_SHARE_PCT,
    names_pt: dict[str, str] | None = None,
) -> dict:
    """Calcula indicadores e pontuação de cada mercado importador.

    flows: comtrade_flows com parceiros 0 e 76 (série histórica)
    partners: comtrade_flows do ano de referência com os demais parceiros
    brazil_exports: ISO3 → exportação brasileira FOB no ano de referência (Comex Stat)
    """
    complete_years = [s["year"] for s in world_series if s["complete"]]
    world = flows[(flows["partner_code"] == WORLD) & (flows["reporter_code"] != BRAZIL)]
    from_br = flows[flows["partner_code"] == BRAZIL]

    cur = world[(world["year"] == ref_year) & (world["value_usd"] > 0)]
    total_world = float(cur["value_usd"].sum())
    br_ref = from_br[from_br["year"] == ref_year].set_index("reporter_code")["value_usd"]
    brazil_world_share = float(br_ref.reindex(cur["reporter_code"]).fillna(0).sum()) / total_world * 100 if total_world else 0.0

    # Concentração (HHI) por importador, a partir do detalhe de fornecedores
    sup = supplier_table(partners)
    sup = sup[sup["value_usd"] > 0]
    # Só há detalhe confiável para importadores com algum fornecedor além do Brasil
    # (as linhas do Brasil vêm da série histórica e existem mesmo sem o detalhe)
    detailed = set(sup.loc[sup["partner_code"] != BRAZIL, "reporter_code"])
    world_ref = cur.set_index("reporter_code")["value_usd"]
    only_brazil = {
        code for code, v in br_ref.items()
        if code not in detailed and code in world_ref and v >= 0.99 * world_ref[code]
    }
    sup = sup[sup["reporter_code"].isin(detailed | only_brazil)]
    hhi, hhi_comp, n_sup, leader = {}, {}, {}, {}
    for code, grp in sup.groupby("reporter_code"):
        shares = grp["value_usd"] / grp["value_usd"].sum()
        hhi[code] = float((shares ** 2).sum())
        # Concentração entre os CONCORRENTES do Brasil (o domínio do próprio Brasil não é barreira)
        comp_grp = grp[grp["partner_code"] != BRAZIL]
        if not comp_grp.empty:
            comp_shares = comp_grp["value_usd"] / comp_grp["value_usd"].sum()
            hhi_comp[code] = float((comp_shares ** 2).sum())
        n_sup[code] = int(len(grp))
        top = grp.loc[grp["value_usd"].idxmax()]
        leader[code] = {"iso3": top["partner_iso"],
                        "country": (names_pt or {}).get(top["partner_iso"]) or top["partner_name"],
                        "share_pct": _r(top["value_usd"] / grp["value_usd"].sum() * 100)}
    br_rank = {}
    for code, grp in sup.groupby("reporter_code"):
        ordered = grp.sort_values("value_usd", ascending=False)["partner_code"].tolist()
        br_rank[code] = ordered.index(BRAZIL) + 1 if BRAZIL in ordered else None

    series_by_country = {
        code: dict(zip(g["year"], g["value_usd"])) for code, g in world.groupby("reporter_code")
    }

    rows, excluded_small = [], 0
    for r in cur.itertuples(index=False):
        share_world = r.value_usd / total_world * 100 if total_world else 0
        if share_world < min_share_pct:
            excluded_small += 1
            continue
        code = int(r.reporter_code)
        values = series_by_country.get(code, {})
        growth, base_year = cagr(values, ref_year, complete_years)
        prev = _f(values.get(ref_year - 1))
        br_val = _f(br_ref.get(code)) or 0.0
        br_share = br_val / r.value_usd * 100
        base_value = _f(values.get(base_year)) if base_year else None
        rows.append({
            "reporter_code": code,
            "iso3": r.reporter_iso,
            "country": r.reporter_name,
            "imports_usd": float(r.value_usd),
            "cagr_base_value_usd": base_value,
            "world_share_pct": share_world,
            "cagr_pct": growth,
            "cagr_base_year": base_year,
            "yoy_pct": (r.value_usd / prev - 1) * 100 if prev else None,
            "imports_from_brazil_usd": br_val,
            "brazil_share_pct": br_share,
            "brazil_gap_pp": brazil_world_share - br_share if brazil_world_share > 0 else None,
            "hhi": hhi.get(code),
            "hhi_competitors": hhi_comp.get(code),
            "suppliers_count": n_sup.get(code),
            "leader": leader.get(code),
            "brazil_supplier_rank": br_rank.get(code),
            "brazil_exports_fob_usd": (brazil_exports or {}).get(r.reporter_iso),
        })

    if not rows:
        return {"markets": [], "brazil_world_share_pct": _r(brazil_world_share), "total_world_usd": total_world,
                "excluded_small": excluded_small}

    df = pd.DataFrame(rows)
    comp = pd.DataFrame(index=df.index)
    comp["market_size"] = _percentile(df["imports_usd"])
    comp["growth"] = _percentile(df["cagr_pct"].astype(float))
    comp["brazil_room"] = _percentile(df["brazil_gap_pp"].astype(float))
    comp["openness"] = _percentile(1 - df["hhi_competitors"].astype(float))
    comp["brazil_presence"] = df["brazil_share_pct"].map(lambda s: 100.0 if s >= 1 else 50.0 if s > 0 else 0.0)
    if brazil_world_share == 0:  # Brasil não exporta o produto: presença não diferencia mercados
        comp["brazil_presence"] = float("nan")

    markets = []
    for i, row in df.iterrows():
        components, wsum, acc = [], 0.0, 0.0
        for key, weight in WEIGHTS.items():
            score = _f(comp.at[i, key])
            if score is not None:
                wsum += weight
                acc += weight * score
            components.append({"key": key, "label": LABELS[key], "weight": weight,
                               "score": _r(score, 1), "value": _indicator_value(key, row)})
        total_score = acc / wsum if wsum else None
        markets.append({
            "iso3": row["iso3"],
            "country": row["country"],
            "reporter_code": int(row["reporter_code"]),
            "score": _r(total_score, 1),
            "completeness_pct": round(wsum / sum(WEIGHTS.values()) * 100),
            "indicators": {
                "imports_usd": _f(row["imports_usd"]),
                "world_share_pct": _r(row["world_share_pct"]),
                "cagr_pct": _r(row["cagr_pct"]),
                "cagr_period": f"{int(row['cagr_base_year'])}–{ref_year}" if _f(row["cagr_base_year"]) else None,
                "cagr_base_value_usd": _f(row["cagr_base_value_usd"]),
                "yoy_pct": _r(row["yoy_pct"]),
                "imports_from_brazil_usd": _f(row["imports_from_brazil_usd"]),
                "brazil_share_pct": _r(row["brazil_share_pct"]),
                "brazil_gap_pp": _r(row["brazil_gap_pp"]),
                "hhi": _r(row["hhi"], 3),
                "hhi_competitors": _r(row["hhi_competitors"], 3),
                "suppliers_count": None if _f(row["suppliers_count"]) is None else int(row["suppliers_count"]),
                "brazil_supplier_rank": None if _f(row["brazil_supplier_rank"]) is None else int(row["brazil_supplier_rank"]),
                "leader_supplier": row["leader"] if isinstance(row["leader"], dict) else None,
                "brazil_exports_fob_usd": _f(row["brazil_exports_fob_usd"]),
            },
            "components": components,
        })
    markets.sort(key=lambda m: (m["score"] is None, -(m["score"] or 0)))
    for pos, m in enumerate(markets, start=1):
        m["rank"] = pos
        m["highlights"] = highlights(m, brazil_world_share)

    return {
        "markets": markets,
        "brazil_world_share_pct": _r(brazil_world_share),
        "total_world_usd": total_world,
        "excluded_small": excluded_small,
    }


def _indicator_value(key: str, row) -> float | None:
    return {
        "market_size": _f(row["imports_usd"]),
        "growth": _r(row["cagr_pct"]),
        "brazil_room": _r(row["brazil_gap_pp"]),
        "openness": None if _f(row["hhi_competitors"]) is None else _r(1 - row["hhi_competitors"], 3),
        "brazil_presence": _r(row["brazil_share_pct"]),
    }[key]


def _fmt_pct(v: float) -> str:
    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".") + "%"


def _fmt_usd(v: float) -> str:
    if v >= 1e9:
        return f"US$ {v / 1e9:.1f} bi".replace(".", ",")
    if v >= 1e6:
        return f"US$ {v / 1e6:.1f} mi".replace(".", ",")
    if v >= 1e3:
        return f"US$ {v / 1e3:.0f} mil"
    return f"US$ {v:.0f}"


# Acima deste crescimento a taxa anual perde sentido (base muito pequena);
# o destaque mostra o salto em valores.
GROWTH_JUMP_PCT = 100


def highlights(m: dict, brazil_world_share: float) -> list[str]:
    """Justificativas objetivas, geradas a partir dos indicadores (sem IA)."""
    ind = m["indicators"]
    comps = {c["key"]: c["score"] for c in m["components"]}
    out = []
    if (comps.get("market_size") or 0) >= 80:
        out.append(f"Entre os maiores importadores ({_fmt_pct(ind['world_share_pct'])} das importações mundiais)")
    if ind["cagr_pct"] is not None:
        if ind["cagr_pct"] >= GROWTH_JUMP_PCT and ind["cagr_base_value_usd"]:
            first = ind["cagr_period"].split("–")[0]
            out.append(
                f"Mercado em formação: importações saltaram de {_fmt_usd(ind['cagr_base_value_usd'])} ({first}) "
                f"para {_fmt_usd(ind['imports_usd'])}"
            )
        elif ind["cagr_pct"] >= 10:
            out.append(f"Importações crescendo {_fmt_pct(ind['cagr_pct'])} ao ano ({ind['cagr_period']})")
        elif ind["cagr_pct"] < 0:
            out.append(f"Importações em queda de {_fmt_pct(abs(ind['cagr_pct']))} ao ano ({ind['cagr_period']})")
    bs = ind["brazil_share_pct"] or 0
    if brazil_world_share > 0:
        if bs == 0:
            out.append("Brasil ainda não fornece a este mercado")
        elif bs < brazil_world_share / 2:
            out.append(f"Participação do Brasil ({_fmt_pct(bs)}) abaixo da média mundial dele ({_fmt_pct(brazil_world_share)})")
        elif bs >= brazil_world_share:
            rank = ind["brazil_supplier_rank"]
            if rank and rank <= 3:
                out.append(f"Brasil já é o {rank}º fornecedor ({_fmt_pct(bs)} do mercado)")
            else:
                pos = f"; {rank}º fornecedor" if rank else ""
                out.append(f"Participação do Brasil ({_fmt_pct(bs)}{pos}) acima da média mundial dele "
                           f"({_fmt_pct(brazil_world_share)})")
    lead = ind["leader_supplier"]
    if ind["hhi"] is not None and lead and lead.get("iso3") != "BRA" and ind["hhi"] >= 0.5:
        out.append(f"Fornecimento concentrado: {lead['country']} detém {_fmt_pct(lead['share_pct'] or 0)}")
    elif ind["hhi_competitors"] is not None and ind["hhi_competitors"] < 0.15:
        out.append("Concorrentes pulverizados (nenhum fornecedor domina)")
    if m["completeness_pct"] < 100:
        out.append(f"Pontuação calculada com {m['completeness_pct']}% dos indicadores (dados parciais)")
    return out
