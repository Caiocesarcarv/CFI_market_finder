# Bibliotecas de terceiros (copiadas localmente para funcionar sem CDN)

| Arquivo | Origem | Versão | Licença |
|---|---|---|---|
| `plotly/plotly-basic.min.js` | plotly.js-basic-dist-min (npm) | 2.35.2 | MIT — Copyright Plotly, Inc. |
| `leaflet/leaflet.js`, `leaflet/leaflet.css` | leaflet (npm) | 1.9.4 | BSD-2-Clause — Copyright Vladimir Agafonkin, CloudMade |
| `geo/world-countries.geojson` | Natural Earth, Admin 0 Countries 1:110m (v5.1.2) | 5.1.2 | Domínio público (naturalearthdata.com) |

O GeoJSON foi reduzido: mantidos apenas `iso3` e `name` (nome em português) e coordenadas
arredondadas para 2 casas decimais.

Para atualizar uma biblioteca, substitua o arquivo pela nova versão e ajuste esta tabela.
