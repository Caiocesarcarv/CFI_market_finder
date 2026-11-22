/**
 * Aplicação: navegação (#/ e #/produto/{id}), status, formulário de pesquisa
 * com identificação de código por IA e lista de pesquisas salvas.
 */
(() => {
  const { el, fmt, badge } = UI;
  const $ = (id) => document.getElementById(id);

  const INTEGRATION_LABELS = {
    comtrade: "UN Comtrade (comércio mundial)",
    comexstat: "Comex Stat (exportações brasileiras)",
    groq: "Groq (inteligência artificial)",
  };

  // ------------------------------------------------------------------ navegação

  function route() {
    const match = location.hash.match(/^#\/produto\/(\d+)/);
    $("view-home").hidden = !!match;
    $("view-dashboard").hidden = !match;
    window.scrollTo(0, 0);
    if (match) {
      Dashboard.open($("view-dashboard"), Number(match[1]));
    } else {
      document.title = "CFI Market Finder";
      loadHistory();
    }
  }

  // ------------------------------------------------------------------ status

  async function loadStatus() {
    const pill = $("app-status");
    const list = $("integrations");
    try {
      const h = await Api.health();
      $("app-version").textContent = `v${h.version}`;
      const missing = Object.values(h.integrations).filter((i) => !i.configured).length;
      if (!h.database.ok) {
        pill.textContent = "Banco de dados indisponível";
        pill.className = "status-pill status-error";
      } else if (missing) {
        pill.textContent = `Online · ${missing} integração(ões) sem chave`;
        pill.className = "status-pill status-warn";
      } else {
        pill.textContent = "Online";
        pill.className = "status-pill status-ok";
      }
      const items = Object.entries(h.integrations).map(([key, info]) => el("li", {}, [
        el("span", { className: `dot ${info.configured ? "dot-ok" : "dot-off"}` }),
        el("span", {}, [el("strong", { textContent: INTEGRATION_LABELS[key] || key }), el("br"),
          el("small", { textContent: `${info.configured ? "Configurada" : "Não configurada"} — ${info.note}` })]),
      ]));
      const ncm = h.reference_tables && h.reference_tables.ncm;
      if (ncm) {
        const ready = ncm.rows > 0;
        items.push(el("li", {}, [
          el("span", { className: `dot ${ready ? "dot-ok" : "dot-off"}` }),
          el("span", { textContent: ready ? `Tabela oficial NCM: ${fmt.int(ncm.rows)} códigos`
            : ncm.status === "error" ? `Tabela oficial NCM: falha ao baixar (${ncm.message || "erro"})` : "Tabela oficial NCM: baixando…" }),
        ]));
        if (!ready && ncm.status !== "error") setTimeout(loadStatus, 5000);
      }
      list.replaceChildren(...items);
    } catch (err) {
      pill.textContent = "Offline";
      pill.className = "status-pill status-error";
      list.replaceChildren(el("li", { className: "muted", textContent: err.message }));
    }
  }

  // ------------------------------------------------------------------ pesquisas salvas

  async function loadHistory() {
    const body = $("history-body");
    try {
      const items = await Api.listSearches();
      if (!items.length) {
        body.replaceChildren(el("tr", {}, [el("td", { colSpan: 6, className: "muted", textContent: "Nenhuma pesquisa ainda. Comece descrevendo um produto acima." })]));
        return;
      }
      body.replaceChildren(...items.map(renderRow));
    } catch (err) {
      body.replaceChildren(el("tr", {}, [el("td", { colSpan: 6, className: "muted", textContent: err.message })]));
    }
  }

  function renderRow(s) {
    const del = el("button", { type: "button", className: "link-btn danger", textContent: "Excluir" });
    del.addEventListener("click", async () => {
      if (!confirm(`Excluir a pesquisa "${s.product_name}"?`)) return;
      try {
        await Api.deleteSearch(s.id);
        loadHistory();
      } catch (err) {
        alert(err.message);
      }
    });
    return el("tr", {}, [
      el("td", {}, [el("a", { href: `#/produto/${s.id}`, textContent: s.product_name })]),
      el("td", { className: "mono", textContent: s.code_input }),
      el("td", { textContent: s.code_type }),
      el("td", { className: "mono", textContent: s.hs_code }),
      el("td", { textContent: fmt.date(s.created_at) }),
      el("td", {}, [el("div", { className: "btn-row" }, [el("a", { className: "btn btn-sm", href: `#/produto/${s.id}`, textContent: "Abrir painel" }), del])]),
    ]);
  }

  // ------------------------------------------------------------------ identificação de código com IA

  function setupAiClassify() {
    const btn = $("ai-btn");
    const panel = $("ai-panel");
    btn.addEventListener("click", async () => {
      const q = $("product_name").value.trim();
      panel.hidden = false;
      if (q.length < 3) {
        panel.replaceChildren(el("span", { className: "hint error", textContent: "Descreva o produto (mínimo 3 caracteres)." }));
        return;
      }
      btn.disabled = true;
      panel.replaceChildren(UI.loading("Consultando a IA e a tabela oficial NCM…"));
      try {
        const r = await Api.classify(q);
        const nodes = [el("div", {}, [badge("estimativa", "Estimativa (IA)"), " ", r.interpretation || ""])];
        if (!r.suggestions.length) {
          nodes.push(el("p", { className: "hint error", textContent: "Nenhuma NCM válida encontrada. Descreva o produto com mais detalhes." }));
        }
        for (const s of r.suggestions) {
          const item = el("button", { type: "button", className: "suggestion" }, [
            el("strong", { className: "mono", textContent: fmt.ncm(s.ncm) }),
            el("span", { className: `conf conf-${s.confidence}`, textContent: `confiança ${s.confidence}` }),
            el("br"), el("span", { textContent: s.official_description }),
            el("br"), el("small", { className: "muted", textContent: s.justification }),
          ]);
          item.addEventListener("click", () => {
            $("code").value = s.ncm;
            $("code").dispatchEvent(new Event("input"));
            panel.hidden = true;
          });
          nodes.push(item);
        }
        if (r.observation) nodes.push(el("p", { className: "disclaimer", textContent: `Obs.: ${r.observation}` }));
        if (r.discarded.length) nodes.push(el("p", { className: "disclaimer", textContent: `${r.discarded.length} sugestão(ões) da IA descartada(s) por não existirem na tabela oficial.` }));
        nodes.push(el("p", { className: "disclaimer", textContent: r.disclaimer }));
        panel.replaceChildren(...nodes);
      } catch (err) {
        panel.replaceChildren(el("span", { className: "hint error", textContent: err.message }));
      } finally {
        btn.disabled = false;
      }
    });
  }

  // ------------------------------------------------------------------ validação do código

  let validateTimer = null;

  function setupCodeValidation() {
    const input = $("code");
    const hint = $("code-hint");
    const defaultHint = hint.textContent;
    input.addEventListener("input", () => {
      clearTimeout(validateTimer);
      const value = input.value.trim();
      input.classList.remove("valid", "invalid");
      hint.className = "hint";
      if (!value) {
        hint.textContent = defaultHint;
        return;
      }
      validateTimer = setTimeout(async () => {
        try {
          const r = await Api.validateCode(value);
          if (input.value.trim() !== value) return;
          if (r.valid) {
            input.classList.add("valid");
            hint.className = "hint ok";
            const desc = r.official_description ? ` — ${r.official_description}` : "";
            hint.textContent = r.code_type === "NCM"
              ? `NCM válida${desc}. Dados internacionais usarão o HS ${r.hs_code}.`
              : `${r.code_type} válido.`;
          } else {
            input.classList.add("invalid");
            hint.className = "hint error";
            hint.textContent = r.message;
          }
        } catch (_) {
          hint.textContent = defaultHint;
        }
      }, 300);
    });
  }

  // ------------------------------------------------------------------ envio

  function setupForm() {
    const form = $("search-form");
    const msg = $("form-message");
    const btn = $("submit-btn");
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = { product_name: $("product_name").value.trim(), code: $("code").value.trim() };
      if (data.product_name.length < 2) {
        msg.className = "form-message error";
        msg.textContent = "Informe o nome do produto (mínimo 2 caracteres).";
        return;
      }
      btn.disabled = true;
      msg.className = "form-message";
      msg.textContent = "Salvando…";
      try {
        const saved = await Api.createSearch(data);
        msg.textContent = "";
        form.reset();
        $("code").classList.remove("valid", "invalid");
        $("code-hint").className = "hint";
        location.hash = `#/produto/${saved.id}`;
      } catch (err) {
        msg.className = "form-message error";
        msg.textContent = err.message;
      } finally {
        btn.disabled = false;
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    setupCodeValidation();
    setupAiClassify();
    setupForm();
    loadStatus();
    window.addEventListener("hashchange", route);
    route();
  });
})();
