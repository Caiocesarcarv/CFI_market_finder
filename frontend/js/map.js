/**
 * Mapa mundial de atratividade (Leaflet + GeoJSON local, sem servidor de mapas).
 *
 * Coroplético sequencial (um tom de azul, claro → escuro) em 5 classes por
 * quintis da pontuação dos mercados avaliados. Países não avaliados em cinza;
 * o Brasil (origem) em verde, identificado na legenda. Funciona offline.
 */
const WorldMap = (() => {
  const { el, fmt, token } = UI;
  let geojsonPromise = null;
  let map = null;

  // Códigos da Comtrade que diferem do ISO3 do mapa
  const ALIASES = { S19: "TWN" }; // "Other Asia, nes" = Taiwan na UN Comtrade

  function loadGeo() {
    if (!geojsonPromise) {
      geojsonPromise = fetch("vendor/geo/world-countries.geojson").then((r) => {
        if (!r.ok) throw new Error("Não foi possível carregar o contorno dos países.");
        return r.json();
      });
    }
    return geojsonPromise;
  }

  /** Limites das 5 classes (quintis) a partir das pontuações. */
  function breaks(scores) {
    const s = scores.filter((v) => v != null).sort((a, b) => a - b);
    if (!s.length) return [];
    return [0.2, 0.4, 0.6, 0.8].map((q) => s[Math.min(s.length - 1, Math.floor(q * s.length))]);
  }

  const classOf = (score, br) => (score == null ? -1 : br.filter((b) => score >= b).length);

  /**
   * container: elemento; markets: lista do ranking; onSelect(iso3) ao clicar.
   */
  let lastArgs = null;

  async function render(container, markets, onSelect) {
    destroy();
    lastArgs = [container, markets, onSelect];
    const geo = await loadGeo();
    const byIso = new Map(markets.map((m) => [ALIASES[m.iso3] || m.iso3, m]));
    const br = breaks(markets.map((m) => m.score));
    const fills = ["--map-1", "--map-2", "--map-3", "--map-4", "--map-5"].map(token);

    map = L.map(container, {
      zoomSnap: 0.25, minZoom: 1, maxZoom: 6, worldCopyJump: false,
      maxBounds: [[-70, -200], [88, 200]], attributionControl: true,
    });
    map.attributionControl.setPrefix("Leaflet");
    map.attributionControl.addAttribution("Fronteiras: Natural Earth");

    const style = (f) => {
      const iso = f.properties.iso3;
      const m = byIso.get(iso);
      let fill = token("--map-none");
      if (iso === "BRA") fill = token("--series-brazil");
      else if (m) fill = fills[Math.max(0, classOf(m.score, br))];
      return { fillColor: fill, fillOpacity: 1, color: token("--map-stroke"), weight: 0.6 };
    };

    const layer = L.geoJSON(geo, {
      filter: (f) => f.properties.iso3 !== "ATA",
      style,
      onEachFeature: (f, lyr) => {
        const iso = f.properties.iso3;
        const m = byIso.get(iso);
        lyr.bindTooltip(() => tooltip(f, m), { sticky: true, className: "map-tip", direction: "top" });
        lyr.on({
          mouseover: () => lyr.setStyle({ weight: 2, color: token("--text") }),
          mouseout: () => layer.resetStyle(lyr),
          click: () => { if (m && onSelect) onSelect(m.iso3); },
        });
      },
    }).addTo(map);

    map.fitBounds([[-55, -168], [78, 180]]);
    legend(br, fills).addTo(map);
    // o contêiner pode ter mudado de tamanho depois de exibido
    setTimeout(() => map && map.invalidateSize(), 50);
  }

  function tooltip(f, m) {
    const name = f.properties.name;
    if (f.properties.iso3 === "BRA") return el("div", {}, [el("strong", { textContent: name }), el("br"), "País de origem"]);
    if (!m) return el("div", {}, [el("strong", { textContent: name }), el("br"), el("span", { className: "muted", textContent: "Fora do ranking (sem dados ou mercado muito pequeno)" })]);
    const i = m.indicators;
    return el("div", {}, [
      el("strong", { textContent: `${m.rank}º ${m.country_pt || name}` }), el("br"),
      `Pontuação: ${fmt.num(m.score)} (estimativa)`, el("br"),
      `Importa: ${fmt.usd(i.imports_usd)}`, el("br"),
      `Crescimento: ${i.cagr_pct == null ? "—" : fmt.signedPct(i.cagr_pct) + " a.a."}`, el("br"),
      `Fatia do Brasil: ${fmt.pct(i.brazil_share_pct)}`, el("br"),
      el("span", { className: "muted", textContent: "Clique para ver o mercado" }),
    ]);
  }

  function legend(br, fills) {
    const ctl = L.control({ position: "bottomleft" });
    ctl.onAdd = () => {
      const labels = br.length
        ? [`< ${fmt.num(br[0], 0)}`, `${fmt.num(br[0], 0)}–${fmt.num(br[1], 0)}`, `${fmt.num(br[1], 0)}–${fmt.num(br[2], 0)}`,
           `${fmt.num(br[2], 0)}–${fmt.num(br[3], 0)}`, `≥ ${fmt.num(br[3], 0)}`]
        : [];
      const box = el("div", { className: "map-legend" }, [el("strong", { textContent: "Pontuação de atratividade" })]);
      [...labels].reverse().forEach((lab, idx) => {
        const fill = fills[labels.length - 1 - idx];
        box.append(el("div", {}, [el("i", { style: `background:${fill}` }), lab]));
      });
      box.append(el("div", {}, [el("i", { style: `background:${token("--map-none")}` }), "Não avaliado"]));
      box.append(el("div", {}, [el("i", { style: `background:${token("--series-brazil")}` }), "Brasil (origem)"]));
      L.DomEvent.disableClickPropagation(box);
      return box;
    };
    return ctl;
  }

  function destroy() {
    if (map) { map.remove(); map = null; }
  }

  // Troca de tema claro/escuro: redesenha com as cores do novo tema
  window.addEventListener("themechange", () => {
    if (map && lastArgs && document.body.contains(lastArgs[0])) render(...lastArgs);
  });

  return { render, destroy };
})();
