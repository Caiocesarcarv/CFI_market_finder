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
    container.replaceChildren(
      el("h3", { textContent: `${search.product_name} — ${search.code_type} ${search.code_digits}` }),
      el("div", { className: "trade-grid" }, [
        imp.status === "fulfilled" ? renderImports(imp.value) : errorBox("Importações mundiais", imp.reason),
        exp.status === "fulfilled" ? renderExports(exp.value) : errorBox("Exportações brasileiras", exp.reason),
      ])
    );
  }

  return { show };
})();
