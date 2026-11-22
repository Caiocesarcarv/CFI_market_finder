/**
 * Utilitários de interface: criação de elementos e formatação pt-BR.
 * Todo texto vindo do servidor entra por textContent (nunca innerHTML).
 */
const UI = (() => {
  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
      if (k === "dataset") Object.assign(node.dataset, v);
      else if (k === "attrs") for (const [a, av] of Object.entries(v)) node.setAttribute(a, av);
      else node[k] = v;
    }
    for (const c of [].concat(children)) if (c !== null && c !== undefined && c !== false) node.append(c);
    return node;
  }

  const nf1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  const nf0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

  const fmt = {
    usd(v) {
      if (v === null || v === undefined) return "—";
      const a = Math.abs(v);
      if (a >= 1e9) return `US$ ${nf1.format(v / 1e9)} bi`;
      if (a >= 1e6) return `US$ ${nf1.format(v / 1e6)} mi`;
      if (a >= 1e3) return `US$ ${nf0.format(v / 1e3)} mil`;
      return `US$ ${nf0.format(v)}`;
    },
    pct(v) { return v === null || v === undefined ? "—" : `${nf1.format(v)}%`; },
    signedPct(v) {
      if (v === null || v === undefined) return "—";
      return `${v > 0 ? "+" : ""}${nf1.format(v)}%`;
    },
    num(v, digits = 1) {
      if (v === null || v === undefined) return "—";
      return new Intl.NumberFormat("pt-BR", { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
    },
    int(v) { return v === null || v === undefined ? "—" : nf0.format(v); },
    date(iso) {
      if (!iso) return "—";
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("pt-BR");
    },
    ncm(code) { return String(code).replace(/^(\d{4})(\d{2})(\d{2})$/, "$1.$2.$3"); },
  };

  const badge = (nature, text) =>
    el("span", { className: `badge badge-${nature}`, textContent: text || { real: "Real", estimativa: "Estimativa", demonstrativo: "Demonstrativo" }[nature] });

  function warnings(list) {
    return list && list.length ? el("ul", { className: "warnings" }, list.map((w) => el("li", { textContent: w }))) : null;
  }

  function loading(text) {
    return el("div", { className: "loading" }, [el("span", { className: "spinner", attrs: { "aria-hidden": "true" } }), el("span", { textContent: text })]);
  }

  function errorNotice(err) {
    return el("p", { className: "notice error", textContent: err && err.message ? err.message : String(err) });
  }

  /** Valor de um token CSS (para gráficos e mapa seguirem o tema). */
  const token = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  return { el, fmt, badge, warnings, loading, errorNotice, token };
})();
