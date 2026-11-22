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
    if (body && Array.isArray(body.detail) && body.detail.length) {
      return body.detail.map((d) => d.msg).join("; ");
    }
    return `Erro ${status} ao comunicar com o servidor.`;
  }

  async function request(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
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

  return {
    ApiError,
    health: () => request("/api/health"),
    listSearches: () => request("/api/searches"),
    createSearch: (data) => request("/api/searches", { method: "POST", body: JSON.stringify(data) }),
    deleteSearch: (id) => request(`/api/searches/${encodeURIComponent(id)}`, { method: "DELETE" }),
    validateCode: (code) => request(`/api/searches/validate-code?code=${encodeURIComponent(code)}`),
    classify: (q) => request(`/api/classify?q=${encodeURIComponent(q)}`),
    worldImports: (code) => request(`/api/trade/${encodeURIComponent(code)}/imports?limit=15`),
    brazilExports: (code) => request(`/api/brazil/${encodeURIComponent(code)}/exports?limit=15`),
    markets: (code) => request(`/api/analysis/${encodeURIComponent(code)}/markets?top=10`),
  };
})();
