/**
 * Painel de um produto (Fase 5): indicadores-chave, gráficos, mapa,
 * ranking de países, mercado selecionado, relatório com IA e dados/fontes.
 */
const Dashboard = (() => {
  const { el, fmt, badge, warnings, loading, errorNotice } = UI;
  let state = null;

  // ------------------------------------------------------------------ carregamento

  async function open(container, searchId, { refresh = false } = {}) {
    Charts.clear();
    WorldMap.destroy();
    container.replaceChildren(loading("Carregando produto…"));

    let search;
    try {
      search = await Api.getSearch(searchId);
    } catch (err) {
      container.replaceChildren(backLink(), errorNotice(err));
      return;
    }
    container.replaceChildren(
      header(search, null),
      loading("Consultando UN Comtrade e Comex Stat e calculando indicadores… a primeira consulta de um produto pode levar até 20 s.")
    );

    let ranking;
    try {
      ranking = await Api.markets(search.code_digits, refresh);
    } catch (err) {
      container.replaceChildren(header(search, null), errorNotice(err));
      return;
    }
    let exportsData = null, exportsErr = null;
    try {
      exportsData = await Api.brazilExports(search.code_digits, refresh);
    } catch (err) {
      exportsErr = err;
    }

    state = { container, search, ranking, exportsData, exportsErr, selected: null, showAll: false };
    render();
  }

  // ------------------------------------------------------------------ estrutura

  function backLink() {
    return el("p", {}, [el("a", { href: "#/", textContent: "← Voltar para as pesquisas" })]);
  }

  function header(search, ranking) {
    const meta = [`${search.code_type} ${search.code_type === "NCM" ? fmt.ncm(search.code_digits) : search.code_digits}`];
    if (search.code_type === "NCM") meta.push(`HS ${search.hs_code} na UN Comtrade`);
    if (ranking) meta.push(`ano de referência ${ranking.reference_year}`, `dados de ${fmt.date(ranking.fetched_at)}`);

    const refreshBtn = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Atualizar dados" });
    refreshBtn.addEventListener("click", () => open(state.container, search.id, { refresh: true }));

    return el("div", {}, [
      backLink(),
      el("div", { className: "dash-header" }, [
        el("div", {}, [el("h1", { textContent: search.product_name }), el("p", { className: "dash-meta", textContent: meta.join(" · ") })]),
        ranking ? el("div", { className: "btn-row no-print" }, [refreshBtn]) : null,
      ]),
    ]);
  }

  function subnav() {
    const items = [
      ["sec-overview", "Visão geral"], ["sec-map", "Mapa"], ["sec-ranking", "Ranking"],
      ["sec-market", "Mercado"], ["sec-report", "Relatório IA"], ["sec-data", "Dados e fontes"],
    ];
    return el("nav", { className: "subnav", attrs: { "aria-label": "Seções do painel" } }, items.map(([id, label]) => {
      const a = el("a", { href: "#", textContent: label });
      a.addEventListener("click", (e) => { e.preventDefault(); document.getElementById(id).scrollIntoView(); });
      return a;
    }));
  }

  function card(title, natureOrNull, sub, body, extraHead) {
    return el("div", { className: "card" }, [
      el("div", { className: "card-head" }, [
        el("div", {}, [
          el("h3", {}, [title, natureOrNull ? " " : "", natureOrNull ? badge(natureOrNull) : null]),
          sub ? el("p", { className: "card-sub", textContent: sub }) : null,
        ]),
        extraHead || null,
      ]),
      ...[].concat(body),
    ]);
  }

  function render() {
    const { container, search, ranking } = state;
    Charts.clear();
    WorldMap.destroy();

    const marketBox = el("div", { id: "market-box" });
    const sections = [
      header(search, ranking),
      subnav(),
      el("section", { id: "sec-overview", className: "stack" }, overview()),
      el("section", { id: "sec-map" }, [el("h2", { className: "section-title", textContent: "Mapa de oportunidades" }), mapCard()]),
      el("section", { id: "sec-ranking" }, [el("h2", { className: "section-title", textContent: "Ranking de países" }), ...rankingSection()]),
      el("section", { id: "sec-market" }, [el("h2", { className: "section-title", textContent: "Mercado selecionado" }), marketBox]),
      el("section", { id: "sec-report" }, [el("h2", { className: "section-title", textContent: "Relatório executivo" }), reportCard()]),
      el("section", { id: "sec-data" }, [el("h2", { className: "section-title", textContent: "Dados e fontes" }), ...dataSection()]),
    ];
    container.replaceChildren(...sections);
    drawOverviewCharts();
    drawRankingCharts();
    WorldMap.render(document.getElementById("world-map"), ranking.markets, (iso) => selectMarket(iso, true))
      .catch((err) => document.getElementById("world-map").replaceWith(errorNotice(err)));
    if (ranking.markets.length) selectMarket(ranking.markets[0].iso3, false);
    else marketBox.replaceChildren(el("p", { className: "notice", textContent: "Nenhum mercado avaliado para este código." }));
  }

  // ------------------------------------------------------------------ visão geral

  function kpi(label, value, detail, nature) {
    return el("div", { className: "card kpi" }, [
      el("div", { className: "kpi-label" }, [label, " ", badge(nature)]),
      el("div", { className: "kpi-value", textContent: value }),
      el("div", { className: "kpi-detail", textContent: detail }),
    ]);
  }

  function lastFullYear(yearly) {
    const full = (yearly || []).filter((y) => !y.partial);
    return full.length ? full[full.length - 1] : null;
  }

  function overview() {
    const { ranking, exportsData, exportsErr } = state;
    const b = ranking.benchmark;
    const g = ranking.global_suppliers;
    const ref = ranking.reference_year;
    const top = ranking.markets[0];

    let expValue = "—", expDetail = exportsErr ? `Indisponível: ${exportsErr.message}` : "Sem exportações registradas";
    let expLabel = "Exportações brasileiras";
    const lf = exportsData && lastFullYear(exportsData.yearly);
    if (lf) {
      const prev = exportsData.yearly.find((y) => y.year === lf.year - 1);
      expLabel = `Exportações do Brasil ${lf.year}`;
      expValue = fmt.usd(lf.fob_usd);
      expDetail = `${prev ? fmt.signedPct((lf.fob_usd / prev.fob_usd - 1) * 100) + " vs " + prev.year + " · " : ""}${lf.destinations} destinos · FOB`;
    }

    return [
      el("div", { className: "kpis" }, [
        kpi(`Importações mundiais ${ref}`, fmt.usd(b.world_imports_usd),
          b.world_yoy_comparable_pct == null ? "Valor declarado pelos importadores"
            : `${fmt.signedPct(b.world_yoy_comparable_pct)} vs ${ref - 1} (países comparáveis)`, "real"),
        kpi("Brasil no mundo", fmt.pct(b.brazil_world_share_pct),
          g.brazil ? `${g.brazil.rank}º exportador entre ${g.exporters}` : "Não aparece entre os exportadores", "real"),
        kpi(expLabel, expValue, expDetail, "real"),
        kpi("Mercado mais atrativo", top ? (top.country_pt || top.country) : "—",
          top ? `Pontuação ${fmt.num(top.score)} · ${b.markets_evaluated} mercados avaliados` : "Sem mercados avaliados", "estimativa"),
      ]),
      warnings(ranking.warnings),
      el("div", { className: "grid-2" }, [
        card("Importações mundiais por ano", "real", "UN Comtrade · soma dos países informantes, US$ correntes",
          [el("div", { id: "chart-world", className: "chart", attrs: { role: "img", "aria-label": "Importações mundiais por ano" } }),
           el("p", { className: "chart-foot", textContent: "Anos hachurados estão incompletos: parte dos países ainda não informou seus dados." })]),
        card("Exportações brasileiras por ano", "real", "Comex Stat · valor FOB, US$ correntes",
          exportsData && exportsData.yearly.length
            ? [el("div", { id: "chart-brazil", className: "chart", attrs: { role: "img", "aria-label": "Exportações brasileiras por ano" } }),
               el("p", { className: "chart-foot", textContent: exportsData.latest_month < 12 ? `${exportsData.latest_year} é parcial (janeiro a ${String(exportsData.latest_month).padStart(2, "0")}/${exportsData.latest_year}).` : "" })]
            : [el("p", { className: "notice", textContent: exportsErr ? `Comex Stat indisponível: ${exportsErr.message}` : "O Comex Stat não registra exportações brasileiras deste código no período." })]),
      ]),
    ];
  }

  function drawOverviewCharts() {
    const { ranking, exportsData } = state;
    Charts.yearBars(document.getElementById("chart-world"), ranking.world_series.map((s) => ({
      year: s.year, value: s.total_usd, partial: !s.complete, partialLabel: "incompleto",
      extra: `<br>${s.reporters} países informantes`,
    })));
    const chartBr = document.getElementById("chart-brazil");
    if (chartBr) {
      Charts.yearBars(chartBr, exportsData.yearly.map((y) => ({
        year: y.year, value: y.fob_usd, partial: y.partial, partialLabel: "parcial",
        extra: `<br>${y.destinations} destinos`,
      })));
    }
  }

  // ------------------------------------------------------------------ mapa

  function mapCard() {
    return card("Atratividade por país", "estimativa",
      "Cores por quintis da pontuação CFI. Passe o mouse para ver os indicadores; clique para abrir o mercado.",
      [el("div", { id: "world-map", className: "map", attrs: { role: "img", "aria-label": "Mapa mundial da pontuação de atratividade por país" } })]);
  }

  // ------------------------------------------------------------------ ranking

  function rankingSection() {
    const { ranking } = state;
    const tableBox = el("div", { id: "ranking-table" });
    renderRankingTable(tableBox);
    const m = ranking.methodology;
    return [
      card("Mercados recomendados", "estimativa",
        `${ranking.benchmark.markets_evaluated} mercados avaliados (${ranking.benchmark.markets_excluded_small} muito pequenos excluídos). ${ranking.data_nature_note}`,
        [tableBox, el("p", { className: "chart-foot", textContent: "Pesos: " + Object.entries(m.weights).map(([k, w]) => `${m.indicators[k].label} ${Math.round(w * 100)}%`).join(" · ") })]),
      el("div", { className: "grid-2", style: "margin-top:16px" }, [
        card("Composição da pontuação — 10 primeiros", "estimativa", "Contribuição de cada indicador para a pontuação final",
          el("div", { id: "chart-breakdown", className: "chart chart-tall", attrs: { role: "img", "aria-label": "Composição da pontuação dos 10 primeiros mercados" } })),
        card("Principais exportadores do mundo", "real", `Segundo o que os importadores declararam em ${ranking.reference_year}`,
          el("div", { id: "chart-exporters", className: "chart chart-tall", attrs: { role: "img", "aria-label": "Principais países exportadores" } })),
      ]),
    ];
  }

  function growthCell(i) {
    if (i.cagr_pct == null) return el("td", { className: "num muted", textContent: "—" });
    if (i.cagr_pct >= 100) return el("td", { className: "num pos", textContent: "salto", title: "Importações partiram de base muito pequena" });
    return el("td", { className: `num ${i.cagr_pct > 0 ? "pos" : i.cagr_pct < 0 ? "neg" : ""}`, textContent: fmt.signedPct(i.cagr_pct) });
  }

  function renderRankingTable(box) {
    const { ranking } = state;
    const rows = state.showAll ? ranking.markets : ranking.markets.slice(0, 20);
    const body = el("tbody", {}, rows.map((m) => {
      const i = m.indicators;
      const open = el("button", { type: "button", className: "link-btn", textContent: "Ver mercado" });
      open.addEventListener("click", () => selectMarket(m.iso3, true));
      return el("tr", { dataset: { iso: m.iso3 }, className: m.iso3 === state.selected ? "selected" : "" }, [
        el("td", { className: "num", textContent: String(m.rank) }),
        el("td", {}, [el("strong", { textContent: m.country_pt || m.country })]),
        el("td", {}, [el("div", { className: "scorebar" }, [
          el("span", { className: "num", textContent: fmt.num(m.score) }),
          el("span", { className: "scorebar-track" }, [el("span", { className: "scorebar-fill", style: `width:${m.score || 0}%;display:block` })]),
        ])]),
        el("td", { className: "num", textContent: fmt.usd(i.imports_usd) }),
        growthCell(i),
        el("td", { className: "num", textContent: fmt.pct(i.brazil_share_pct) }),
        el("td", { className: "why", textContent: m.highlights.join(" · ") }),
        el("td", {}, [open]),
      ]);
    }));
    const table = el("div", { className: "table-wrap" }, [el("table", { className: "table" }, [
      el("thead", {}, [el("tr", {}, ["#", "Mercado", "Pontuação", "Importa", "Cresc. a.a.", "Fatia do Brasil", "Por quê", ""]
        .map((h, idx) => el("th", { className: [0, 3, 4, 5].includes(idx) ? "num" : "", textContent: h })))]),
      body,
    ])]);
    const parts = [table];
    if (ranking.markets.length > 20) {
      const more = el("button", { type: "button", className: "btn btn-secondary btn-sm",
        textContent: state.showAll ? "Mostrar só os 20 primeiros" : `Mostrar todos os ${ranking.markets.length}` });
      more.addEventListener("click", () => { state.showAll = !state.showAll; renderRankingTable(box); });
      parts.push(el("div", { className: "btn-row", style: "margin-top:10px" }, [more]));
    }
    box.replaceChildren(...parts);
  }

  function drawRankingCharts() {
    const { ranking } = state;
    const top10 = ranking.markets.slice(0, 10);
    if (top10.length) Charts.scoreBreakdown(document.getElementById("chart-breakdown"), top10, ranking.methodology);

    const g = ranking.global_suppliers;
    const items = g.top.map((s) => ({ label: s.country_pt || s.country, value: s.value_usd, share: s.share_pct, highlight: s.iso3 === "BRA" }));
    if (g.brazil && !g.top.some((s) => s.iso3 === "BRA")) {
      items.push({ label: `${g.brazil.country_pt || "Brasil"} (${g.brazil.rank}º)`, value: g.brazil.value_usd, share: g.brazil.share_pct, highlight: true });
    }
    if (items.length) Charts.rankBars(document.getElementById("chart-exporters"), items);
  }

  // ------------------------------------------------------------------ mercado selecionado

  async function selectMarket(iso3, scroll) {
    state.selected = iso3;
    document.querySelectorAll("#ranking-table tr[data-iso]").forEach((tr) => tr.classList.toggle("selected", tr.dataset.iso === iso3));
    const box = document.getElementById("market-box");
    if (!box) return;
    if (scroll) document.getElementById("sec-market").scrollIntoView();
    box.replaceChildren(loading("Carregando mercado…"));
    try {
      const detail = await Api.marketDetail(state.search.code_digits, iso3);
      if (state.selected !== iso3) return; // usuário escolheu outro enquanto carregava
      renderMarket(box, detail);
    } catch (err) {
      box.replaceChildren(errorNotice(err));
    }
  }

  function renderMarket(box, d) {
    const m = d.market, i = m.indicators;
    const name = m.country_pt || m.country;
    const aiBox = el("div", { className: "ai-box" });
    const aiBtn = el("button", { type: "button", className: "btn btn-sm", textContent: `Gerar análise de ${name} com IA` });
    const product = state.search.product_name;
    const generate = (refresh) => Report.run(aiBox, `Gerando análise de ${name}`,
      () => Api.aiCountry(state.search.code_digits, m.iso3, product, refresh),
      (r) => Report.country(r, aiActions(r)));
    const aiActions = () => {
      const again = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Gerar novamente" });
      again.addEventListener("click", () => generate(true));
      return [el("a", { className: "btn btn-secondary btn-sm", href: Api.aiCountryMdUrl(state.search.code_digits, m.iso3, product), textContent: "Baixar .md" }), again];
    };
    aiBtn.addEventListener("click", async () => { aiBtn.disabled = true; await generate(false); aiBtn.disabled = false; });

    const brazilPos = i.brazil_supplier_rank ? `${i.brazil_supplier_rank}º fornecedor` : (i.brazil_share_pct ? "" : "não fornece");
    const growth = i.cagr_pct == null ? "—" : i.cagr_pct >= 100 ? "salto" : fmt.signedPct(i.cagr_pct);

    box.replaceChildren(card(
      `${m.rank}º ${name}`, "estimativa",
      `${d.in_main_ranking ? `Posição entre ${d.rank_among} mercados avaliados` : `Fora do ranking principal (mercado pequeno); posição entre ${d.rank_among} importadores`} · pontuação ${fmt.num(m.score)} (${m.completeness_pct}% dos indicadores)`,
      [
        el("div", { className: "market-kpis" }, [
          el("div", {}, [el("span", { textContent: `Importações ${d.reference_year}` }), el("strong", { textContent: fmt.usd(i.imports_usd) })]),
          el("div", {}, [el("span", { textContent: `Crescimento ${i.cagr_period || ""}` }), el("strong", { textContent: growth + (i.cagr_pct != null && i.cagr_pct < 100 ? " a.a." : "") })]),
          el("div", {}, [el("span", { textContent: "Fatia do Brasil" }), el("strong", { textContent: `${fmt.pct(i.brazil_share_pct)}${brazilPos ? " · " + brazilPos : ""}` })]),
          el("div", {}, [el("span", { textContent: "Exportação BR (Comex Stat)" }), el("strong", { textContent: fmt.usd(i.brazil_exports_fob_usd) })]),
        ]),
        m.highlights.length ? el("ul", { className: "highlights" }, m.highlights.map((h) => el("li", { textContent: h }))) : null,
        warnings(d.warnings.filter((w) => !state.ranking.warnings.includes(w))),
        el("div", { className: "grid-2", style: "margin-top:12px" }, [
          el("div", {}, [el("h3", {}, ["Importações por ano ", badge("real")]),
            el("div", { id: "chart-market-history", className: "chart", attrs: { role: "img", "aria-label": `Importações de ${name} por ano` } })]),
          el("div", {}, [el("h3", {}, [`Fornecedores em ${d.reference_year} `, badge("real")]),
            el("div", { id: "chart-market-suppliers", className: "chart", attrs: { role: "img", "aria-label": `Principais fornecedores de ${name}` } })]),
        ]),
        el("h3", { style: "margin-top:12px", textContent: "Como a pontuação foi formada" }),
        el("div", { className: "table-wrap" }, [el("table", { className: "table" }, [
          el("thead", {}, [el("tr", {}, ["Indicador", "Valor", "Percentil", "Peso"].map((h, idx) => el("th", { className: idx ? "num" : "", textContent: h })))]),
          el("tbody", {}, m.components.map((c) => el("tr", {}, [
            el("td", { textContent: c.label }),
            el("td", { className: "num", textContent: componentValue(c) }),
            el("td", { className: "num", textContent: c.score == null ? "sem dado" : fmt.num(c.score, 0) }),
            el("td", { className: "num", textContent: `${Math.round(c.weight * 100)}%` }),
          ]))),
        ])]),
        el("div", { className: "btn-row no-print", style: "margin-top:14px" }, [aiBtn]),
        aiBox,
      ]));

    const incomplete = new Set(d.incomplete_years || []);
    Charts.yearBars(document.getElementById("chart-market-history"), d.history.map((h) => ({
      year: h.year, value: h.value_usd, partial: incomplete.has(h.year), partialLabel: "incompleto",
    })));
    const sup = d.suppliers.slice(0, 7).map((s) => ({ label: s.country_pt || s.country, value: s.value_usd, share: s.share_pct, highlight: s.iso3 === "BRA" }));
    const brazil = d.suppliers.find((s) => s.iso3 === "BRA");
    if (brazil && brazil.rank > 7) sup.push({ label: `Brasil (${brazil.rank}º)`, value: brazil.value_usd, share: brazil.share_pct, highlight: true });
    const rest = d.suppliers.filter((s) => s.rank > 7 && s.iso3 !== "BRA");
    if (rest.length) {
      sup.push({ label: `Outros (${rest.length})`, value: rest.reduce((a, s) => a + s.value_usd, 0),
        share: rest.reduce((a, s) => a + (s.share_pct || 0), 0), highlight: false });
    }
    const supEl = document.getElementById("chart-market-suppliers");
    if (sup.length) Charts.rankBars(supEl, sup);
    else supEl.replaceWith(el("p", { className: "notice", textContent: "Sem detalhamento de fornecedores para este país." }));
  }

  function componentValue(c) {
    if (c.value == null) return "—";
    switch (c.key) {
      case "market_size": return fmt.usd(c.value);
      case "growth": return `${fmt.signedPct(c.value)} a.a.`;
      case "brazil_room": return `${fmt.num(c.value)} p.p.`;
      case "openness": return fmt.num(c.value, 2);
      case "brazil_presence": return fmt.pct(c.value);
      default: return String(c.value);
    }
  }

  // ------------------------------------------------------------------ relatório

  function reportCard() {
    const out = el("div", { className: "ai-box" });
    const product = state.search.product_name;
    const code = state.search.code_digits;
    const btn = el("button", { type: "button", className: "btn", textContent: "Gerar relatório executivo com IA" });

    const actions = () => {
      const print = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Imprimir / salvar PDF" });
      print.addEventListener("click", () => {
        document.body.classList.add("print-report");
        window.print();
      });
      const again = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Gerar novamente" });
      again.addEventListener("click", () => generate(true));
      return [el("a", { className: "btn btn-secondary btn-sm", href: Api.aiReportMdUrl(code, product), textContent: "Baixar .md" }), print, again];
    };
    const generate = async (refresh) => {
      btn.disabled = true;
      const r = await Report.run(out, "Gerando relatório executivo", () => Api.aiReport(code, product, refresh), (res) => Report.report(res, actions()));
      btn.hidden = !!r;
      btn.disabled = false;
    };
    btn.addEventListener("click", () => generate(false));

    return card("Relatório executivo com IA", "estimativa",
      "A IA interpreta o ranking e os indicadores acima. Os valores citados são conferidos automaticamente com os dados; revise o texto antes de compartilhar.",
      [el("div", { className: "btn-row no-print" }, [btn]), out]);
  }

  window.addEventListener("afterprint", () => document.body.classList.remove("print-report"));

  // ------------------------------------------------------------------ dados e fontes

  function dataSection() {
    const { ranking, exportsData, exportsErr } = state;
    const byImports = [...ranking.markets].sort((a, b) => (b.indicators.imports_usd || 0) - (a.indicators.imports_usd || 0)).slice(0, 20);
    const importers = el("table", { className: "table" }, [
      el("thead", {}, [el("tr", {}, ["País", "Importa", "% mundo", "Var. anual", "Do Brasil"].map((h, i) => el("th", { className: i ? "num" : "", textContent: h })))]),
      el("tbody", {}, byImports.map((m) => el("tr", {}, [
        el("td", { textContent: m.country_pt || m.country }),
        el("td", { className: "num", textContent: fmt.usd(m.indicators.imports_usd) }),
        el("td", { className: "num", textContent: fmt.pct(m.indicators.world_share_pct) }),
        el("td", { className: "num", textContent: fmt.signedPct(m.indicators.yoy_pct) }),
        el("td", { className: "num", textContent: fmt.usd(m.indicators.imports_from_brazil_usd) }),
      ]))),
    ]);

    let destinations;
    if (exportsData && exportsData.destinations.length) {
      destinations = el("table", { className: "table" }, [
        el("thead", {}, [el("tr", {}, ["Destino", "FOB", "Participação"].map((h, i) => el("th", { className: i ? "num" : "", textContent: h })))]),
        el("tbody", {}, exportsData.destinations.slice(0, 20).map((x) => el("tr", {}, [
          el("td", { textContent: x.country }),
          el("td", { className: "num", textContent: fmt.usd(x.reference_year_fob_usd) }),
          el("td", { className: "num", textContent: fmt.pct(x.share_pct) }),
        ]))),
      ]);
    } else {
      destinations = el("p", { className: "notice", textContent: exportsErr ? `Comex Stat indisponível: ${exportsErr.message}` : "Sem exportações registradas." });
    }

    const m = ranking.methodology;
    return [
      el("div", { className: "grid-2" }, [
        card(`Maiores importadores ${ranking.reference_year}`, "real", "UN Comtrade · valor declarado pelo importador (geralmente CIF)",
          el("div", { className: "table-wrap" }, [importers])),
        card(`Destinos das exportações brasileiras ${exportsData ? exportsData.reference_year : ""}`, "real", "Comex Stat · valor FOB",
          [el("div", { className: "table-wrap" }, [destinations]), exportsData ? warnings(exportsData.warnings) : null]),
      ]),
      el("div", { style: "margin-top:16px" }, [card("Metodologia e fontes", null, null, [
        el("ul", { className: "highlights" }, [
          el("li", { textContent: `Importações: UN Comtrade, ${ranking.years[0]}–${ranking.years[ranking.years.length - 1]}; dados obtidos em ${fmt.date(ranking.fetched_at)}.` }),
          el("li", { textContent: `Exportações brasileiras: Comex Stat (MDIC)${exportsData ? `, dados até ${String(exportsData.latest_month).padStart(2, "0")}/${exportsData.latest_year}` : ""}.` }),
          el("li", { textContent: `Pontuação (estimativa): ${Object.entries(m.weights).map(([k, w]) => `${m.indicators[k].label} ${Math.round(w * 100)}%`).join("; ")}. ${m.normalization}` }),
          ...Object.values(m.indicators).map((ind) => el("li", { textContent: `${ind.label}: ${ind.description}` })),
          el("li", { textContent: m.values }),
        ]),
      ])]),
    ];
  }

  return { open };
})();
