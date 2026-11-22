/**
 * Prévia dos dados comerciais reais de um produto (Fase 2).
 * Tabelas simples; gráficos e mapa entram na Fase 5.
 */
const TradeView = (() => {
  const fmtUsd = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "USD", notation: "compact", maximumFractionDigits: 1 });
  const fmtPct = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1, signDisplay: "exceptZero" });

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.assign(node, props);
    for (const c of children) node.append(c);
    return node;
  }
  const fmtShare = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const usd = (v) => (v == null ? "—" : fmtUsd.format(v));
  const share = (v) => (v == null ? "—" : `${fmtShare.format(v)}%`);
  function pctCell(v) {
    if (v == null) return el("td", { className: "num muted", textContent: "—" });
    return el("td", { className: `num ${v > 0 ? "pos" : v < 0 ? "neg" : ""}`, textContent: `${fmtPct.format(v)}%` });
  }

  function header(title, body) {
    const date = body.fetched_at ? new Date(body.fetched_at).toLocaleString("pt-BR") : "—";
    const nodes = [
      el("h3", {}, [title, " ", el("span", { className: "badge badge-real", textContent: "Real" })]),
      el("p", {
        className: "meta",
        textContent: `Fonte: ${body.source} · obtido em ${date}${body.from_cache ? " (cache)" : ""}`,
      }),
    ];
    if (body.warnings && body.warnings.length) {
      nodes.push(el("ul", { className: "warnings" }, body.warnings.map((w) => el("li", { textContent: w }))));
    }
    return nodes;
  }

  function table(head, rows) {
    return el("div", { className: "table-wrap" }, [
      el("table", { className: "table" }, [
        el("thead", {}, [el("tr", {}, head.map(([t, cls]) => el("th", { className: cls || "", textContent: t })))]),
        el("tbody", {}, rows),
      ]),
    ]);
  }

  function renderImports(body) {
    const rows = body.importers.map((i, idx) =>
      el("tr", {}, [
        el("td", { textContent: String(idx + 1) }),
        el("td", { textContent: i.country_pt || i.country }),
        el("td", { className: "num", textContent: usd(i.value_usd) }),
        el("td", { className: "num", textContent: share(i.world_share_pct) }),
        pctCell(i.yoy_pct),
        el("td", { className: "num", textContent: usd(i.imports_from_brazil_usd) }),
      ])
    );
    return el("div", {}, [
      ...header(`Maiores importadores — HS ${body.hs_code} (${body.year})`, body),
      rows.length
        ? table([["#"], ["País"], ["Importado", "num"], ["% mundo", "num"], ["Var. anual", "num"], ["Do Brasil", "num"]], rows)
        : el("p", { className: "muted", textContent: "Sem dados de importação para este código." }),
      el("p", { className: "meta", textContent: body.value_note || "" }),
    ]);
  }

  function renderExports(body) {
    const ref = body.reference_year;
    const rows = body.destinations.map((d, idx) =>
      el("tr", {}, [
        el("td", { textContent: String(idx + 1) }),
        el("td", { textContent: d.country }),
        el("td", { className: "num", textContent: usd(d.reference_year_fob_usd) }),
        el("td", { className: "num", textContent: share(d.share_pct) }),
      ])
    );
    const yearly = body.yearly
      .map((y) => `${y.year}${y.partial ? "*" : ""}: ${usd(y.fob_usd)}`)
      .join(" · ");
    return el("div", {}, [
      ...header(`Exportações brasileiras — ${body.code_type} ${body.code}`, body),
      yearly ? el("p", { className: "meta", textContent: `Total por ano (FOB): ${yearly}${body.yearly.some((y) => y.partial) ? "  (* parcial)" : ""}` }) : "",
      rows.length
        ? table([["#"], [`Destino (${ref})`], ["FOB", "num"], ["Participação", "num"]], rows)
        : el("p", { className: "muted", textContent: "Sem exportações brasileiras registradas." }),
    ]);
  }

  function renderMarkets(body, search) {
    const b = body.benchmark;
    const br = body.global_suppliers.brazil;
    const aiOut = el("div", { className: "ai-out" });

    const reportBtn = el("button", { type: "button", className: "secondary", textContent: "Gerar relatório executivo (IA)" });
    reportBtn.addEventListener("click", async () => {
      reportBtn.disabled = true;
      await AiView.run(aiOut, "Gerando relatório executivo com IA",
        () => Api.aiReport(search.code_digits, search.product_name),
        (r) => AiView.report(r, Api.aiReportMdUrl(search.code_digits, search.product_name)));
      reportBtn.disabled = false;
    });

    const aiLink = (m) => {
      const btn = el("button", { type: "button", className: "link action", textContent: "Análise IA" });
      btn.addEventListener("click", () =>
        AiView.run(aiOut, `Gerando análise de ${m.country_pt || m.country} com IA`,
          () => Api.aiCountry(search.code_digits, m.iso3, search.product_name), AiView.country));
      return btn;
    };

    const rows = body.markets.map((m) =>
      el("tr", {}, [
        el("td", { textContent: String(m.rank) }),
        el("td", {}, [el("strong", { textContent: m.country_pt || m.country })]),
        el("td", { className: "num", textContent: m.score == null ? "—" : m.score.toLocaleString("pt-BR") }),
        el("td", { className: "num", textContent: usd(m.indicators.imports_usd) }),
        m.indicators.cagr_pct != null && m.indicators.cagr_pct >= 100
          ? el("td", { className: "num pos", textContent: "salto", title: `${m.indicators.cagr_pct}% a.a. (base muito pequena)` })
          : pctCell(m.indicators.cagr_pct),
        el("td", { className: "num", textContent: share(m.indicators.brazil_share_pct) }),
        el("td", {}, [el("small", { textContent: m.highlights.join(" · ") })]),
        el("td", {}, [aiLink(m)]),
      ])
    );
    const date = body.fetched_at ? new Date(body.fetched_at).toLocaleString("pt-BR") : "—";
    return el("div", {}, [
      el("h3", {}, [
        `Mercados recomendados — referência ${body.reference_year} `,
        el("span", { className: "badge badge-estimativa", textContent: "Estimativa" }),
      ]),
      el("p", { className: "meta", textContent: `${body.source} · dados obtidos em ${date}. ${body.data_nature_note}` }),
      el("p", {
        className: "meta",
        textContent:
          `Brasil: ${share(b.brazil_world_share_pct)} das importações mundiais` +
          (br ? ` (${br.rank}º exportador)` : "") +
          ` · ${b.markets_evaluated} mercados avaliados (${b.markets_excluded_small} muito pequenos excluídos).`,
      }),
      body.warnings.length ? el("ul", { className: "warnings" }, body.warnings.map((w) => el("li", { textContent: w }))) : "",
      table([["#"], ["Mercado"], ["Pontuação", "num"], ["Importa", "num"], ["Cresc. a.a.", "num"], ["Fatia BR", "num"], ["Por quê"], [""]], rows),
      el("p", {
        className: "meta",
        textContent: "Pesos: " + Object.entries(body.methodology.weights)
          .map(([k, w]) => `${body.methodology.indicators[k].label} ${Math.round(w * 100)}%`).join(" · "),
      }),
      reportBtn,
      aiOut,
    ]);
  }

  function errorBox(title, err) {
    return el("div", {}, [el("h3", { textContent: title }), el("p", { className: "form-message error", textContent: err.message })]);
  }

  /** Busca as duas fontes em paralelo; a falha de uma não impede a outra. */
  async function show(search, container) {
    container.replaceChildren(
      el("h3", { textContent: `${search.product_name} — ${search.code_type} ${search.code_digits}` }),
      el("p", { className: "muted", textContent: "Consultando UN Comtrade e Comex Stat… (a primeira consulta pode levar alguns segundos)" })
    );
    const [imp, exp] = await Promise.allSettled([
      Api.worldImports(search.code_digits),
      Api.brazilExports(search.code_digits),
    ]);
    // O ranking reaproveita os dados já em cache das consultas acima
    const [mk] = await Promise.allSettled([Api.markets(search.code_digits)]);
    container.replaceChildren(
      el("h3", { textContent: `${search.product_name} — ${search.code_type} ${search.code_digits}` }),
      mk.status === "fulfilled" ? renderMarkets(mk.value, search) : errorBox("Mercados recomendados", mk.reason),
      el("div", { className: "trade-grid" }, [
        imp.status === "fulfilled" ? renderImports(imp.value) : errorBox("Importações mundiais", imp.reason),
        exp.status === "fulfilled" ? renderExports(exp.value) : errorBox("Exportações brasileiras", exp.reason),
      ])
    );
  }

  return { show };
})();
