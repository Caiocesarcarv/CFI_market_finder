/**
 * Tema claro/escuro.
 * - Sem escolha salva, segue o tema do sistema (e acompanha mudanças dele).
 * - O botão do topo alterna e salva a escolha no navegador (localStorage).
 * - Ao trocar, dispara o evento "themechange" para gráficos e mapa se redesenharem.
 * - Na impressão usa sempre o tema claro.
 */
const Theme = (() => {
  const KEY = "cfi-theme";
  const media = window.matchMedia("(prefers-color-scheme: dark)");

  const ICONS = {
    // sol: mostrado no tema escuro (clique → claro)
    sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    // lua: mostrada no tema claro (clique → escuro)
    moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>',
  };

  function saved() {
    try { return localStorage.getItem(KEY); } catch (_) { return null; }
  }

  const current = () => document.documentElement.dataset.theme === "dark" ? "dark" : "light";

  function apply(theme) {
    if (current() === theme && document.documentElement.dataset.theme) return;
    document.documentElement.dataset.theme = theme;
    updateButton();
    window.dispatchEvent(new CustomEvent("themechange", { detail: { theme } }));
  }

  function toggle() {
    const next = current() === "dark" ? "light" : "dark";
    try { localStorage.setItem(KEY, next); } catch (_) { /* navegador sem armazenamento: vale só nesta visita */ }
    apply(next);
  }

  function updateButton() {
    const btn = document.getElementById("theme-toggle");
    if (!btn) return;
    const dark = current() === "dark";
    const label = dark ? "Mudar para o modo claro" : "Mudar para o modo escuro";
    btn.innerHTML = dark ? ICONS.sun : ICONS.moon; // ícones fixos, sem dados externos
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }

  // Sistema mudou de tema e o usuário nunca escolheu: acompanha
  media.addEventListener("change", (e) => { if (!saved()) apply(e.matches ? "dark" : "light"); });

  // Impressão sempre em tema claro
  let beforePrint = null;
  window.addEventListener("beforeprint", () => { beforePrint = current(); if (beforePrint === "dark") apply("light"); });
  window.addEventListener("afterprint", () => { if (beforePrint === "dark") apply("dark"); beforePrint = null; });

  document.addEventListener("DOMContentLoaded", () => {
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.addEventListener("click", toggle);
    updateButton();
  });

  return { current, toggle };
})();
