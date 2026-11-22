/**
 * Gráficos (Plotly.js, pacote "basic" local em vendor/).
 *
 * Convenções (guia de visualização):
 * - uma série por gráfico sempre que possível (sem legenda; o título nomeia);
 * - cor = papel: azul (série principal), verde (Brasil), cinza (demais);
 *   anos incompletos/parciais em tom claro + hachura + rótulo (nunca só cor);
 * - barras com cantos de 4px, grade recessiva, um único eixo Y;
 * - tooltip em toda marca, com valores já formatados em pt-BR.
 * As cores vêm dos tokens CSS, então o gráfico segue o tema claro/escuro.
 */
const Charts = (() => {
  const { token, fmt } = UI;
  const registry = new Map(); // elemento -> função de render (para trocar de tema)

  const config = { displayModeBar: false, responsive: true };

  function scaleFor(maxValue) {
    if (maxValue >= 1e9) return { div: 1e9, unit: "US$ bilhões" };
    if (maxValue >= 1e6) return { div: 1e6, unit: "US$ milhões" };
    if (maxValue >= 1e3) return { div: 1e3, unit: "US$ mil" };
    return { div: 1, unit: "US$" };
  }

  function axis(extra = {}) {
    return {
      color: token("--axis"), gridcolor: token("--grid"), linecolor: token("--grid"),
      zeroline: false, tickfont: { size: 11 }, automargin: true, fixedrange: true, ...extra,
    };
  }

  function layout(extra = {}) {
    return {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { family: getComputedStyle(document.body).fontFamily, size: 12, color: token("--text-2") },
      margin: { l: 10, r: 16, t: 10, b: 10 },
      separators: ",.",
      showlegend: false,
      bargap: 0.35,
      barcornerradius: 4,
      hoverlabel: { bgcolor: token("--surface"), bordercolor: token("--border"), font: { color: token("--text"), size: 12 } },
      xaxis: axis({ showgrid: false }),
      yaxis: axis(),
      ...extra,
    };
  }

  // Reajusta o gráfico quando o cartão muda de largura (layout responsivo, troca de tela)
  const resizer = typeof ResizeObserver !== "undefined"
    ? new ResizeObserver((entries) => {
      for (const e of entries) if (e.target.classList.contains("js-plotly-plot")) Plotly.Plots.resize(e.target);
    })
    : null;

  function draw(el, render) {
    registry.set(el, render);
    render();
    if (resizer) resizer.observe(el);
  }

  /**
   * Barras por ano. items: [{year, value, partial, partialLabel}]
   */
  function yearBars(el, items, { partialLabel = "incompleto" } = {}) {
    draw(el, () => {
      const max = Math.max(0, ...items.map((i) => i.value || 0));
      const s = scaleFor(max);
      const color = items.map((i) => (i.partial ? token("--bar-partial") : token("--series-1")));
      Plotly.react(el, [{
        type: "bar",
        x: items.map((i) => String(i.year)),
        y: items.map((i) => (i.value == null ? null : i.value / s.div)),
        marker: { color, pattern: { shape: items.map((i) => (i.partial ? "/" : "")), fgcolor: token("--series-1"), size: 6, solidity: 0.25 } },
        text: items.map((i) => (i.partial ? (i.partialLabel || partialLabel) : "")),
        textposition: "outside",
        textfont: { size: 11, color: token("--text-3") },
        cliponaxis: false,
        customdata: items.map((i) => [fmt.usd(i.value), i.partial ? ` (${i.partialLabel || partialLabel})` : "", i.extra || ""]),
        hovertemplate: "<b>%{x}</b>%{customdata[1]}<br>%{customdata[0]}%{customdata[2]}<extra></extra>",
      }], layout({ yaxis: axis({ title: { text: s.unit, font: { size: 11 } }, rangemode: "tozero" }) }), config);
    });
  }

  /**
   * Barras horizontais ordenadas (maior em cima). items: [{label, value, share, highlight}]
   */
  function rankBars(el, items, { highlightLabel = "Brasil" } = {}) {
    draw(el, () => {
      const rows = [...items].reverse();
      const max = Math.max(0, ...rows.map((i) => i.value || 0));
      const s = scaleFor(max);
      Plotly.react(el, [{
        type: "bar",
        orientation: "h",
        y: rows.map((i) => i.label),
        x: rows.map((i) => i.value / s.div),
        marker: { color: rows.map((i) => (i.highlight ? token("--series-brazil") : token("--bar-neutral"))) },
        text: rows.map((i) => (i.share == null ? "" : fmt.pct(i.share))),
        textposition: "outside",
        textfont: { size: 11, color: token("--text-2") },
        cliponaxis: false,
        customdata: rows.map((i) => [fmt.usd(i.value), i.share == null ? "" : ` · ${fmt.pct(i.share)}`, i.highlight ? ` (${highlightLabel})` : ""]),
        hovertemplate: "<b>%{y}</b>%{customdata[2]}<br>%{customdata[0]}%{customdata[1]}<extra></extra>",
      }], layout({
        bargap: 0.3,
        margin: { l: 10, r: 50, t: 4, b: 10 },
        xaxis: axis({ title: { text: s.unit, font: { size: 11 } }, rangemode: "tozero", showgrid: true }),
        yaxis: axis({ showgrid: false }),
      }), config);
    });
  }

  /**
   * Decomposição da pontuação: barras empilhadas com a contribuição de cada
   * indicador (peso × percentil, reescalado pelos pesos disponíveis).
   */
  function scoreBreakdown(el, markets, methodology) {
    draw(el, () => {
      const keys = Object.keys(methodology.weights);
      const colors = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5"].map(token);
      const rows = [...markets].reverse();
      const traces = keys.map((key, idx) => ({
        type: "bar",
        orientation: "h",
        name: methodology.indicators[key].label,
        y: rows.map((m) => m.country_pt || m.country),
        x: rows.map((m) => contribution(m, key)),
        marker: { color: colors[idx], line: { color: token("--surface"), width: 2 } },
        customdata: rows.map((m) => {
          const c = m.components.find((x) => x.key === key);
          return [c && c.score != null ? fmt.num(c.score, 0) : "sem dado", fmt.num(contribution(m, key)), fmt.num(m.score)];
        }),
        hovertemplate: `<b>%{y}</b><br>${methodology.indicators[key].label}: percentil %{customdata[0]}` +
          "<br>Contribuição: %{customdata[1]} pts (total %{customdata[2]})<extra></extra>",
      }));
      Plotly.react(el, traces, layout({
        barmode: "stack",
        bargap: 0.3,
        barcornerradius: 0,
        showlegend: true,
        legend: { orientation: "h", x: 0, xanchor: "left", y: 1.01, yanchor: "bottom", font: { size: 11, color: token("--text-2") } },
        margin: { l: 10, r: 16, t: 64, b: 10 },
        xaxis: axis({ title: { text: "Pontuação (0–100)", font: { size: 11 } }, range: [0, 100], showgrid: true }),
        yaxis: axis({ showgrid: false }),
      }), config);
    });
  }

  function contribution(m, key) {
    const available = m.components.filter((c) => c.score != null);
    const wsum = available.reduce((a, c) => a + c.weight, 0);
    const c = m.components.find((x) => x.key === key);
    if (!c || c.score == null || !wsum) return 0;
    return (c.weight * c.score) / wsum;
  }

  function rerenderAll() {
    for (const [el, render] of registry) {
      if (document.body.contains(el)) render();
      else registry.delete(el);
    }
  }

  function clear() {
    for (const el of registry.keys()) {
      if (resizer) resizer.unobserve(el);
      Plotly.purge(el);
    }
    registry.clear();
  }

  window.addEventListener("themechange", rerenderAll);

  return { yearBars, rankBars, scoreBreakdown, rerenderAll, clear };
})();
