/**
 * Exibição dos textos gerados por IA: análise por país e relatório executivo.
 * Sempre com selo "Estimativa (IA)", resultado da conferência automática de
 * números e aviso de uso.
 */
const Report = (() => {
  const { el, fmt, badge } = UI;
  const PRIO = { alta: "Alta", media: "Média", baixa: "Baixa" };
  const TERM = { curto: "curto prazo", medio: "médio prazo", longo: "longo prazo" };

  const section = (title, ...nodes) => el("section", {}, [el("h4", { textContent: title }), ...nodes]);
  const para = (text) => el("p", { textContent: text || "—" });
  const list = (items) => (items && items.length ? el("ul", {}, items.map((t) => el("li", { textContent: t }))) : para("—"));

  function verification(v) {
    if (v.ok) return el("p", { className: "ai-check ok", textContent: `✓ Conferência automática: os ${v.numbers_checked} valores citados conferem com os dados da plataforma.` });
    const parts = [];
    if (v.unverified && v.unverified.length) parts.push(`valores sem correspondência nos dados, desconsidere: ${v.unverified.join(", ")}`);
    if (v.rejected_markets) parts.push(`mercados fora da lista avaliada foram descartados: ${v.rejected_markets.join(", ")}`);
    return el("p", { className: "ai-check bad", textContent: `⚠ Conferência automática — ${parts.join("; ")}.` });
  }

  function header(r, title, actions) {
    return [
      el("div", { className: "card-head" }, [
        el("div", {}, [
          el("h3", {}, [title, " ", badge("estimativa", "Estimativa (IA)")]),
          el("p", { className: "card-sub", textContent: `${r.source} · gerado em ${fmt.date(r.generated_at)}${r.from_cache ? " (salvo)" : ""}` }),
        ]),
        actions ? el("div", { className: "btn-row" }, actions) : null,
      ]),
      verification(r.verification),
    ];
  }

  function recs(items, withTerm) {
    if (!items || !items.length) return para("—");
    return el("ul", {}, items.map((x) => el("li", {}, [
      el("strong", { textContent: `${PRIO[x.prioridade] || x.prioridade}${withTerm ? " · " + (TERM[x.prazo] || x.prazo) : ""}: ` }),
      `${x.acao}. `,
      el("span", { className: "muted", textContent: x.justificativa }),
    ])));
  }

  function country(r, actions) {
    const c = r.content;
    return el("div", { className: "ai-output" }, [
      ...header(r, `Análise de ${r.market.country}`, actions),
      section("Resumo", para(c.resumo)),
      el("div", { className: "grid-2" }, [section("Oportunidades", list(c.oportunidades)), section("Riscos", list(c.riscos))]),
      section("Concorrência", para(c.concorrencia)),
      section("Estratégia de entrada", list(c.estrategia_entrada)),
      section("Recomendações", recs(c.recomendacoes, false)),
      section("Pontos a verificar (fora dos dados)", list(c.pontos_a_verificar)),
      el("p", { className: "disclaimer", textContent: r.disclaimer }),
    ]);
  }

  function report(r, actions) {
    const c = r.content;
    const b = r.benchmark;
    return el("div", { className: "ai-output" }, [
      ...header(r, c.titulo, actions),
      el("p", { className: "card-sub", textContent: `${r.product} · referência ${r.reference_year} · importações mundiais ${fmt.usd(b.world_imports_usd)} · Brasil ${fmt.pct(b.brazil_world_share_pct)} do mundo` }),
      section("Sumário executivo", para(c.sumario_executivo)),
      section("Panorama mundial", para(c.panorama_mundial)),
      section("Mercados prioritários", ...(c.mercados_prioritarios.length ? c.mercados_prioritarios.map((p) =>
        el("div", { className: "ai-market" }, [
          el("strong", { textContent: `${p.pais} — ${p.rank}º no ranking, pontuação ${fmt.num(p.score)}` }),
          el("p", {}, [el("strong", { textContent: "Por quê: " }), p.justificativa]),
          el("p", {}, [el("strong", { textContent: "Como abordar: " }), p.estrategia]),
        ])) : [para("—")])),
      section("Recomendações", recs(c.recomendacoes, true)),
      el("div", { className: "grid-2" }, [
        section("Riscos e limitações", list(c.riscos_e_limitacoes)),
        section("Próximos passos", list(c.proximos_passos)),
      ]),
      section("Metodologia",
        para("Pontuação de atratividade (estimativa CFI): " + Object.entries(r.methodology.weights)
          .map(([k, w]) => `${r.methodology.indicators[k].label} ${Math.round(w * 100)}%`).join("; ") + ". " + r.methodology.values)),
      el("p", { className: "disclaimer", textContent: r.disclaimer }),
    ]);
  }

  /**
   * Prepara a impressão de um único bloco: copia o conteúdo para #print-root,
   * que é a única coisa visível no modo de impressão (ver styles.css).
   * O documento começa direto no texto, sem cabeçalho da página nem página em branco.
   */
  function preparePrint(source) {
    let root = document.getElementById("print-root");
    if (!root) {
      root = el("div", { id: "print-root" });
      document.body.append(root);
    }
    root.replaceChildren(source.cloneNode(true));
    document.body.classList.add("printing");
  }

  function clearPrint() {
    document.body.classList.remove("printing");
    const root = document.getElementById("print-root");
    if (root) root.replaceChildren();
  }

  /** Abre a janela de impressão do navegador (onde se escolhe "Salvar como PDF"). */
  function print(source) {
    preparePrint(source);
    window.print();
  }

  window.addEventListener("afterprint", clearPrint);

  /** Botão "Imprimir / salvar PDF" para um bloco de texto da IA. */
  function printButton(getSource) {
    const btn = el("button", { type: "button", className: "btn btn-secondary btn-sm", textContent: "Imprimir / salvar PDF" });
    btn.addEventListener("click", () => print(getSource()));
    return btn;
  }

  /** Executa uma geração mostrando progresso e erro no container. */
  async function run(container, label, fn, render) {
    container.replaceChildren(UI.loading(`${label}… (até ~15 s)`));
    try {
      const result = await fn();
      container.replaceChildren(render(result));
      return result;
    } catch (err) {
      container.replaceChildren(UI.errorNotice(err));
      return null;
    }
  }

  return { country, report, run, print, preparePrint, printButton };
})();
