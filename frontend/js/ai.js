/**
 * Exibição das análises geradas por IA (Fase 4): análise por país e relatório executivo.
 * Prévia simples; o layout final do relatório entra na Fase 5.
 */
const AiView = (() => {
  const PRIO = { alta: "Alta", media: "Média", baixa: "Baixa" };
  const TERM = { curto: "curto prazo", medio: "médio prazo", longo: "longo prazo" };

  function el(tag, props = {}, children = []) {
    const node = document.createElement(tag);
    Object.assign(node, props);
    for (const c of children) node.append(c);
    return node;
  }
  const section = (title, ...nodes) => el("div", { className: "ai-section" }, [el("h4", { textContent: title }), ...nodes]);
  const para = (text) => el("p", { textContent: text || "—" });
  const list = (items) => el("ul", {}, (items || []).map((t) => el("li", { textContent: t })));

  function header(r, title) {
    const v = r.verification;
    const date = new Date(r.generated_at).toLocaleString("pt-BR");
    const nodes = [
      el("h3", {}, [title, " ", el("span", { className: "badge badge-estimativa", textContent: "Estimativa (IA)" })]),
      el("p", { className: "meta", textContent: `${r.source} · gerado em ${date}${r.from_cache ? " (cache)" : ""}` }),
    ];
    if (v.ok) {
      nodes.push(el("p", { className: "hint ok", textContent: `✓ Os ${v.numbers_checked} valores citados conferem com os dados da plataforma.` }));
    } else {
      const parts = [];
      if (v.unverified.length) parts.push(`valores sem correspondência nos dados (desconsidere): ${v.unverified.join(", ")}`);
      if (v.rejected_markets) parts.push(`mercados fora da lista descartados: ${v.rejected_markets.join(", ")}`);
      nodes.push(el("p", { className: "hint error", textContent: `⚠ Conferência automática: ${parts.join("; ")}.` }));
    }
    return nodes;
  }

  function recs(items, withTerm) {
    return el("ul", {}, (items || []).map((x) =>
      el("li", {}, [
        el("strong", { textContent: `${PRIO[x.prioridade] || x.prioridade}${withTerm ? " · " + (TERM[x.prazo] || x.prazo) : ""}: ` }),
        `${x.acao}. `,
        el("span", { className: "muted", textContent: x.justificativa }),
      ])
    ));
  }

  function country(r) {
    const c = r.content;
    return el("div", { className: "ai-output" }, [
      ...header(r, `Análise de ${r.market.country}`),
      section("Resumo", para(c.resumo)),
      section("Oportunidades", list(c.oportunidades)),
      section("Riscos", list(c.riscos)),
      section("Concorrência", para(c.concorrencia)),
      section("Estratégia de entrada", list(c.estrategia_entrada)),
      section("Recomendações", recs(c.recomendacoes, false)),
      section("Pontos a verificar (fora dos dados)", list(c.pontos_a_verificar)),
      el("p", { className: "disclaimer", textContent: r.disclaimer }),
    ]);
  }

  function report(r, mdUrl) {
    const c = r.content;
    return el("div", { className: "ai-output" }, [
      ...header(r, c.titulo),
      el("p", {}, [el("a", { href: mdUrl, textContent: "Baixar relatório (.md)" })]),
      section("Sumário executivo", para(c.sumario_executivo)),
      section("Panorama mundial", para(c.panorama_mundial)),
      section("Mercados prioritários", ...c.mercados_prioritarios.map((p) =>
        el("div", { className: "ai-market" }, [
          el("strong", { textContent: `${p.pais} (posição ${p.rank}, pontuação ${p.score == null ? "—" : p.score.toLocaleString("pt-BR")})` }),
          el("p", { textContent: `Por quê: ${p.justificativa}` }),
          el("p", { textContent: `Como abordar: ${p.estrategia}` }),
        ])
      )),
      section("Recomendações", recs(c.recomendacoes, true)),
      section("Riscos e limitações", list(c.riscos_e_limitacoes)),
      section("Próximos passos", list(c.proximos_passos)),
      el("p", { className: "disclaimer", textContent: r.disclaimer }),
    ]);
  }

  /** Executa uma geração mostrando progresso e erro no container. */
  async function run(container, label, fn, render) {
    container.replaceChildren(el("p", { className: "muted", textContent: `${label}… (até ~15 s)` }));
    try {
      container.replaceChildren(render(await fn()));
    } catch (err) {
      container.replaceChildren(el("p", { className: "form-message error", textContent: err.message }));
    }
    container.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  return { country, report, run };
})();
