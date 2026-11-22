/**
 * Cliente HTTP da API do CFI Market Finder.
 * Centraliza chamadas e tratamento de erros (rede fora, servidor fora, validação).
 */
const Api = (() => {
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  /** Extrai uma mensagem legível das respostas de erro do FastAPI. */
  function errorMessage(body, status) {
    if (body && typeof body.detail === "string") return body.detail;
    if (body && Array.isArray(body.detail) && body.detail.length) return body.detail.map((d) => d.msg).join("; ");
    return `Erro ${status} ao comunicar com o servidor.`;
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    } catch (err) {
      throw new ApiError("Servidor indisponível. Verifique se o run.bat está em execução.", 0);
    }
    if (response.status === 204) return null;
    let body = null;
    try {
      body = await response.json();
    } catch (_) {
      /* resposta sem JSON */
    }
    if (!response.ok) throw new ApiError(errorMessage(body, response.status), response.status);
    return body;
  }

  const enc = encodeURIComponent;
  const qs = (params) => {
    const s = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ""));
    return s.toString() ? `?${s}` : "";
  };

  return {
    ApiError,
    health: () => request("/api/health"),
    // produtos / pesquisas
    listSearches: () => request("/api/searches"),
    getSearch: (id) => request(`/api/searches/${enc(id)}`),
    createSearch: (data) => request("/api/searches", { method: "POST", body: JSON.stringify(data) }),
    deleteSearch: (id) => request(`/api/searches/${enc(id)}`, { method: "DELETE" }),
    validateCode: (code) => request(`/api/searches/validate-code${qs({ code })}`),
    classify: (q) => request(`/api/classify${qs({ q })}`),
    // dados e análise
    markets: (code, refresh) => request(`/api/analysis/${enc(code)}/markets${qs({ top: 250, refresh: refresh ? "true" : "" })}`),
    marketDetail: (code, iso3) => request(`/api/analysis/${enc(code)}/markets/${enc(iso3)}`),
    brazilExports: (code, refresh) => request(`/api/brazil/${enc(code)}/exports${qs({ limit: 30, refresh: refresh ? "true" : "" })}`),
    // IA
    aiCountry: (code, iso3, product, refresh) =>
      request(`/api/ai/${enc(code)}/markets/${enc(iso3)}${qs({ product, refresh: refresh ? "true" : "" })}`),
    aiReport: (code, product, refresh) => request(`/api/ai/${enc(code)}/report${qs({ product, refresh: refresh ? "true" : "" })}`),
    aiReportMdUrl: (code, product) => `/api/ai/${enc(code)}/report${qs({ product, format: "md" })}`,
    aiCountryMdUrl: (code, iso3, product) => `/api/ai/${enc(code)}/markets/${enc(iso3)}${qs({ product, format: "md" })}`,
  };
})();
