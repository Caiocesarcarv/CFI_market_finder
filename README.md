# CFI Market Finder 1.0

Plataforma local de inteligência de mercados internacionais para identificar
oportunidades de exportação para empresas brasileiras.

O usuário descreve um produto; a IA sugere a classificação NCM/HS (sempre
conferida na tabela oficial). A plataforma então consulta
estatísticas reais (UN Comtrade e Comex Stat) e indica países potencialmente
interessantes para exportação.

> **Princípio:** nenhum dado comercial é inventado. Todo número exibido é
> rotulado como **Real** (fonte oficial), **Estimativa** (cálculo/projeção ou IA) ou
> **Demonstrativo** (exemplo ilustrativo).

## Como executar (Windows)

1. Instale o **Python 3.10+** ([python.org](https://www.python.org/downloads/)) marcando *Add python.exe to PATH*.
2. Dê duplo clique em **`run.bat`**.
   - Na primeira execução ele cria o `venv`, instala as dependências e cria o `.env`.
   - Também baixa, em segundo plano, as tabelas oficiais NCM e de países (~2 minutos).
3. Preencha as chaves no arquivo `.env` (veja `.env.example`) e execute o `run.bat` novamente.
4. O navegador abre em <http://127.0.0.1:8000>. A documentação da API fica em `/docs`.

Opções: `run.bat --no-browser` (não abre o navegador) e `run.bat --reload` (recarrega ao editar o código).

### Execução manual (qualquer sistema)

```bash
python -m venv venv
venv\Scripts\activate          # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python -m app
```

### Testes

```bash
venv\Scripts\python -m pytest -q
```

Os testes simulam as APIs externas: não usam internet nem gastam cota.

## Variáveis de ambiente (`.env`)

| Variável | Uso |
|---|---|
| `APP_HOST`, `APP_PORT` | Endereço do servidor local (padrão `127.0.0.1:8000`) |
| `DATABASE_PATH` | Arquivo SQLite (padrão `data/cfi_market_finder.db`) |
| `COMTRADE_API_KEY` | Chave da UN Comtrade (`UNCOMTRADE_KEY` também é aceito) |
| `GROQ_API_KEY`, `GROQ_MODEL` | Inferência de IA via Groq (padrão `openai/gpt-oss-120b`) |

O Comex Stat é público e não exige chave.

> **Nunca coloque chaves reais no `.env.example`**: ele é versionado no git. As chaves ficam só no `.env`.

## Fontes de dados

| Fonte | O que fornece | Como é obtida |
|---|---|---|
| **UN Comtrade** (API v1) | Importações anuais de cada país por código HS, do mundo e do Brasil | Uma requisição por código; cache de 7 dias |
| **Comex Stat** (API MDIC) | Exportações brasileiras por NCM, ano e destino; tabela NCM; países (ISO3) | Automática; cache de 7 dias |
| **Comex Stat** (CSV) | Mesmos dados de exportação, a partir dos arquivos oficiais `EXP_AAAA.csv` | Importação manual (veja abaixo) |
| **Groq** | Interpretação do nome do produto → NCM | Sob demanda; cache de 30 dias |

Cuidados de interpretação:

- **Cobertura da Comtrade**: os anos recentes chegam incompletos (países reportam com atraso).
  A API marca cada ano como completo ou incompleto e calcula a variação anual só com países
  presentes nos dois anos (`yoy_comparable_pct`).
- **NCM × HS**: a Comtrade usa o HS6 internacional; uma NCM de 8 dígitos é consultada pelos
  6 primeiros dígitos, que podem incluir outras NCMs.
- **Valores**: Comtrade = valor declarado pelo importador (geralmente CIF); Comex Stat = FOB.
- **Ano corrente** no Comex Stat é parcial e vem marcado como tal.
- **Falhas de API**: se uma fonte estiver fora do ar, a aplicação usa os últimos dados salvos
  (com aviso) ou devolve erro claro. Ela nunca preenche a falta com valores fictícios.

## Motor de análise (Fase 3)

Para cada país importador do produto, a plataforma calcula indicadores a partir de dados reais
e combina-os numa **pontuação de atratividade (0–100)**, rotulada como **Estimativa**:

| Indicador | Peso | Como é medido |
|---|---|---|
| Tamanho do mercado | 30% | Valor importado no ano de referência (último ano completo na Comtrade) |
| Crescimento | 25% | CAGR das importações em até 3 anos completos |
| Espaço para o Brasil | 20% | Participação mundial do Brasil no produto − participação do Brasil no país |
| Abertura a fornecedores | 15% | 1 − HHI dos fornecedores concorrentes (excluindo o Brasil) |
| Presença brasileira | 10% | 100 se o Brasil tem ≥ 1% do mercado, 50 se < 1%, 0 se não fornece |

- Cada indicador vira percentil entre os mercados avaliados. Se um indicador faltar, os pesos são
  reescalados e o campo `completeness_pct` mostra a cobertura.
- Mercados com menos de 0,05% das importações mundiais ficam fora do ranking principal (`min_share_pct`).
- Cada mercado traz justificativas objetivas (`highlights`) geradas a partir dos indicadores, sem IA.
- A participação do Brasil usa os dados espelho (o que cada país declara ter importado do Brasil);
  a exportação brasileira do Comex Stat é exibida como referência (`brazil_exports_fob_usd`).

## Inteligência artificial (Fase 4)

A IA (Groq) **interpreta** os indicadores; ela não produz dados.

- **Análise por país:** resumo, oportunidades, riscos, concorrência, estratégia de entrada,
  recomendações priorizadas e pontos a verificar.
- **Relatório executivo:** sumário, panorama mundial, 3 a 5 mercados prioritários (escolhidos
  apenas entre os mercados avaliados), recomendações com prioridade e prazo, riscos e próximos passos.
  Pode ser baixado em Markdown (`format=md`).

Salvaguardas:

1. A IA recebe uma **ficha de dados** com números já calculados e formatados, mais um guia de leitura
   dos indicadores. Os prompts ([app/services/prompts.py](app/services/prompts.py)) proíbem
   números novos, nomes próprios fora da ficha (feiras, empresas, programas) e afirmações sobre
   tarifas, barreiras ou acordos. Esses temas só podem aparecer em "pontos a verificar".
2. **Conferência automática:** todo valor em US$ e % do texto gerado é comparado com a ficha.
   O que não confere aparece em `verification.unverified` e é destacado na tela e no relatório.
   Mercados sugeridos fora da lista avaliada são descartados.
3. Todo texto gerado é rotulado como **Estimativa**. Fica em cache por 7 dias e pode ser
   regenerado com `refresh=true`.

Limitação: a conferência valida **números**, não o raciocínio. A IA ainda pode tirar conclusões
imprecisas a partir de números corretos, então o texto deve ser revisado antes de circular.
O plano gratuito do Groq limita a **8.000 tokens por minuto**, o que permite cerca de 1 relatório
ou 2 análises por minuto. Acima disso, a aplicação pede para aguardar.

### Importar CSV do Comex Stat (opcional)

Baixe os arquivos `EXP_AAAA.csv` em
[Base de dados bruta – MDIC](https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta),
coloque-os em `data\comexstat\` e execute:

```bash
venv\Scripts\python -m app.tools.comexstat_cli import               # todos os EXP_*.csv da pasta
venv\Scripts\python -m app.tools.comexstat_cli import arquivo.csv --ncm 09   # só o capítulo 09
venv\Scripts\python -m app.tools.comexstat_cli sync                 # rebaixar tabelas NCM e países
```

## Estrutura

```
CFI_market_finder/
├── app/                        Backend (FastAPI)
│   ├── __main__.py             Inicialização (python -m app): porta, navegador, Uvicorn
│   ├── main.py                 Criação da aplicação, rotas, erros e frontend estático
│   ├── config.py               Leitura do .env
│   ├── database.py             SQLite + migrações (PRAGMA user_version)
│   ├── models.py               Modelos Pydantic e natureza dos dados
│   ├── api/                    Rotas HTTP (/api/...)
│   │   ├── health.py           Status
│   │   ├── searches.py         Produtos cadastrados e validação de código
│   │   ├── reference.py        Tabela NCM e sugestão de código por IA
│   │   ├── trade.py            Importações mundiais e exportações brasileiras
│   │   ├── analysis.py         Ranking de mercados e detalhe por país
│   │   └── ai.py               Análise por país e relatório executivo (IA)
│   ├── services/               Regras de negócio e integrações
│   │   ├── http.py             Cliente HTTP com novas tentativas e erros em português
│   │   ├── cache.py            Validade do cache das consultas
│   │   ├── classification.py   Validação estrutural HS/NCM
│   │   ├── reference.py        Sincronização e busca na tabela NCM / países
│   │   ├── comtrade.py         UN Comtrade
│   │   ├── comexstat.py        Comex Stat (API e CSV)
│   │   ├── evolution.py        Evolução histórica (Pandas)
│   │   ├── analysis.py         Indicadores, pontuação e ranking de mercados
│   │   ├── markets.py          Montagem do ranking e do detalhe por país
│   │   ├── groq_client.py      Cliente Groq
│   │   ├── prompts.py          Prompts especializados e guia de leitura
│   │   ├── ai_insights.py      Análise por país, relatório executivo e conferência de números
│   │   └── ncm_ai.py           Produto → NCM com IA + validação oficial
│   └── tools/comexstat_cli.py  Linha de comando (sync / import CSV)
├── frontend/                   HTML, CSS e JavaScript puro
├── tests/                      Testes automatizados (pytest, APIs simuladas)
├── data/                       Banco SQLite e CSVs (criados automaticamente, fora do git)
├── .env.example
├── requirements.txt
└── run.bat
```

## API

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | Status do banco, integrações e tabelas oficiais |
| GET | `/api/classify?q=` | Sugere NCMs para a descrição do produto (IA, validada na tabela oficial) |
| GET | `/api/ncm/search?q=` | Busca textual na tabela NCM oficial |
| GET | `/api/ncm/{código}` | Descrição oficial de uma NCM (ou NCMs de um prefixo HS) |
| GET/POST/DELETE | `/api/searches` | Produtos cadastrados |
| GET | `/api/searches/validate-code?code=` | Valida um código HS/NCM |
| GET | `/api/trade/{código}/imports` | Ranking de importadores (Comtrade) com cobertura por ano |
| GET | `/api/trade/{código}/evolution` | Evolução histórica mundial e por país |
| GET | `/api/brazil/{código}/exports` | Exportações brasileiras por ano e destino (Comex Stat) |
| GET | `/api/analysis/{código}/markets` | Ranking de mercados recomendados, com indicadores, pontuação e metodologia |
| GET | `/api/analysis/{código}/markets/{ISO3}` | Detalhe de um mercado: pontuação, série histórica e todos os fornecedores |
| GET | `/api/ai/{código}/markets/{ISO3}` | Análise do mercado gerada por IA (`format=md` para baixar) |
| GET | `/api/ai/{código}/report` | Relatório executivo gerado por IA (`format=md` para baixar) |
| GET/POST | `/api/reference/status`, `/api/reference/sync` | Estado / nova sincronização das tabelas |

As rotas de dados aceitam `refresh=true` para ignorar o cache.

## Cronograma

- [x] **Fase 1 — Fundação:** estrutura, ambiente Python, FastAPI, SQLite, frontend servido pelo FastAPI.
- [x] **Fase 2 — Integração de dados:** UN Comtrade por código HS, importações por país, evolução
      histórica, Comex Stat (API + importação de CSV) e interpretação do produto → NCM com IA.
- [x] **Fase 3 — Motor de análise:** crescimento, principais fornecedores, participação brasileira,
      pontuação de atratividade e ranking de mercados.
- [x] **Fase 4 — Inteligência artificial:** prompts especializados, análises por país, recomendações e relatório executivo.
- [ ] **Fase 5 — Interface:** dashboard, ranking, gráficos (Plotly.js) e mapa (Leaflet), com as
      bibliotecas copiadas para `frontend/vendor/` para funcionar sem CDN.
- [ ] **Fase 6 — Testes e empacotamento:** testes de cenários reais e de falha, revisão do run.bat,
      requirements e README, teste em ambiente limpo.
