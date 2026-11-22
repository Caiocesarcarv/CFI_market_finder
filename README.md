# CFI Market Finder 1.0

Plataforma local de inteligência de mercados internacionais para identificar
oportunidades de exportação para empresas brasileiras.

Você descreve um produto e a IA sugere a classificação NCM, sempre conferida na tabela
oficial. A plataforma então consulta estatísticas reais (UN Comtrade e Comex Stat),
calcula indicadores e mostra em painel, mapa e relatório quais países são mais
interessantes para exportar.

> **Princípio:** nenhum dado comercial é inventado. Todo número exibido é rotulado como
> **Real** (fonte oficial), **Estimativa** (cálculo da plataforma ou texto de IA) ou
> **Demonstrativo** (exemplo ilustrativo).

---

## Instalação (Windows)

### O que é preciso

| Item | Detalhe |
|---|---|
| Windows 10 ou 11 | testado no Windows 11 |
| **Python 3.12 ou mais novo** | [python.org/downloads](https://www.python.org/downloads/). Durante a instalação, marque **"Add python.exe to PATH"**. Testado com 3.12 e 3.13. |
| Internet | para instalar as dependências e consultar os dados (a interface funciona sem CDN) |
| Chave da UN Comtrade | gratuita, veja abaixo |
| Chave do Groq | gratuita, veja abaixo (opcional: sem ela, as funções de IA ficam desligadas) |

Não é necessário Node.js, Docker nem servidor externo.

### Passo a passo

1. Copie a pasta do projeto para o computador (ou `git clone`).
2. Dê duplo clique em **`run.bat`**. Na primeira vez ele:
   - encontra um Python 3.12+ e cria o ambiente virtual `venv`;
   - instala as dependências do `requirements.txt` (cerca de 1 minuto);
   - cria o arquivo `.env` a partir do `.env.example`;
   - inicia o servidor e abre o navegador em <http://127.0.0.1:8000>;
   - baixa em segundo plano as tabelas oficiais NCM e de países (cerca de 2 minutos).
3. Feche a janela do `run.bat`, abra o arquivo **`.env`** no Bloco de Notas e preencha as chaves:
   ```
   COMTRADE_API_KEY=sua chave da UN Comtrade
   GROQ_API_KEY=sua chave do Groq
   ```
4. Dê duplo clique em **`diagnostico.bat`** para confirmar que está tudo certo. Ele testa
   Python, dependências, chaves, banco de dados e a conexão com cada API.
5. Abra o **`run.bat`** novamente. Nas próximas vezes, ele inicia em poucos segundos.

### Como obter as chaves

- **UN Comtrade:** crie uma conta em <https://comtradedeveloper.un.org>, entre em
  *Products* → **comtrade - v1** → *Subscribe* (plano gratuito). A chave aparece em
  *Profile* → *Subscriptions* (*Primary key*). O plano gratuito permite cerca de 500 consultas
  por dia; cada produto novo usa no máximo 2 por semana, graças ao cache.
- **Groq:** crie uma conta em <https://console.groq.com> e gere uma chave em **API Keys**.
  O plano gratuito permite cerca de 8.000 tokens por minuto (≈ 1 relatório ou 2 análises
  por minuto).
- **Comex Stat:** público, não precisa de chave.

> As chaves ficam **somente** no `.env`, que não vai para o git. Nunca coloque chaves reais
> no `.env.example`.

### Opções do run.bat

| Comando | Efeito |
|---|---|
| `run.bat` | inicia normalmente e abre o navegador |
| `run.bat --no-browser` | inicia sem abrir o navegador |
| `run.bat --reload` | recarrega o servidor ao editar o código (desenvolvimento) |
| `run.bat --diagnostico` ou `diagnostico.bat` | verifica ambiente, chaves e conexões |

### Solução de problemas

| Sintoma | O que fazer |
|---|---|
| "Python 3.12 ou mais novo não encontrado" | Instale o Python 3.12+ marcando "Add python.exe to PATH" e abra o `run.bat` de novo. |
| "A pasta venv foi criada com um Python anterior ao 3.12" | Apague a pasta `venv` e abra o `run.bat` de novo. |
| "Não foi possível instalar as dependências" | Verifique a internet ou o proxy da rede; depois abra o `run.bat` de novo. |
| "A porta 8000 já está em uso" | O sistema provavelmente já está aberto em outra janela. Se não estiver, mude `APP_PORT` no `.env`. |
| "Chave de API não configurada" / "chave inválida" | Confira o `.env` e rode o `diagnostico.bat`. |
| "Limite de uso por minuto do Groq" | Aguarde cerca de 1 minuto. Textos já gerados ficam salvos e não gastam cota de novo. |
| "Tabela oficial NCM: baixando…" | Aguarde alguns segundos na primeira execução. |
| Uma fonte de dados fora do ar | O sistema usa os últimos dados salvos (com aviso) ou mostra o erro; nunca inventa valores. |

Execução manual, sem o `run.bat` (Windows, Linux ou macOS, com Python 3.12+):

```bash
python -m venv venv
venv\Scripts\activate            # Linux/macOS: source venv/bin/activate
pip install -r requirements.txt
python -m app
```

---

## Como usar

1. **Nova pesquisa:** descreva o produto (ex.: "café verde em grão") e clique em
   **Identificar código com IA**. Escolha uma das NCMs sugeridas, todas conferidas na tabela
   oficial, ou digite o código HS/NCM. Depois clique em **Analisar mercados**.
2. **Painel do produto:**
   - **Visão geral:** importações mundiais, participação do Brasil, exportações brasileiras e
     mercado mais atrativo, com a evolução anual em gráficos;
   - **Mapa:** países coloridos pela pontuação de atratividade; clique em um país para abri-lo;
   - **Ranking:** todos os mercados avaliados, com justificativas e a composição da pontuação;
   - **Mercado:** histórico, fornecedores, formação da pontuação e **análise com IA**;
   - **Relatório IA:** relatório executivo para download (`.md`) ou impressão/PDF;
   - **Dados e fontes:** tabelas com os números reais e a metodologia.
3. O ícone ☾/☀ no topo alterna entre modo claro e escuro (a escolha fica salva).

A primeira análise de um produto leva de 10 a 20 segundos (consulta às APIs). As seguintes
são instantâneas, porque os dados ficam em cache por 7 dias. "Atualizar dados" força nova consulta.

---

## Testes

```bash
venv\Scripts\python -m pytest              # 89 testes, APIs simuladas (sem internet, sem gastar cota)
```

Os testes cobrem validação de códigos, banco, integrações, cache, cálculo dos indicadores,
pontuação, IA (conferência de números, descarte de códigos e mercados inventados), falhas de
conexão, chaves inválidas, limites de uso, ausência de dados e o frontend servido localmente.

Testes com as **APIs reais** (usam as chaves do `.env` e um banco temporário; custam ~2
consultas à Comtrade e ~6 mil tokens do Groq):

```bash
set CFI_LIVE_TESTS=1
venv\Scripts\python -m pytest -m live -v
```

---

## Fontes de dados e cuidados de interpretação

| Fonte | O que fornece | Como é obtida |
|---|---|---|
| **UN Comtrade** (API v1) | Importações anuais de cada país por código HS, com detalhe por fornecedor | Até 2 requisições por código; cache de 7 dias |
| **Comex Stat** (API do MDIC) | Exportações brasileiras por NCM, ano e destino; tabela NCM; países (ISO3) | Automática; cache de 7 dias |
| **Comex Stat** (CSV) | Mesmos dados de exportação, a partir dos arquivos oficiais `EXP_AAAA.csv` | Importação opcional (veja abaixo) |
| **Groq** | Produto → NCM; análises por país; relatório executivo | Sob demanda; cache de 7 a 30 dias |

- **Cobertura da Comtrade:** os anos recentes chegam incompletos (os países informam com atraso).
  Esses anos aparecem marcados, e a variação anual compara só países presentes nos dois anos.
- **NCM × HS:** a Comtrade usa o HS6 internacional; uma NCM de 8 dígitos é consultada pelos
  6 primeiros dígitos, que podem incluir outras NCMs.
- **Valores:** Comtrade = valor declarado pelo importador (geralmente CIF); Comex Stat = FOB.
- **Ano corrente** no Comex Stat é parcial e vem marcado como tal.

### Pontuação de atratividade (estimativa)

| Indicador | Peso | Como é medido |
|---|---|---|
| Tamanho do mercado | 30% | Valor importado no ano de referência (último ano completo na Comtrade) |
| Crescimento | 25% | CAGR das importações em até 3 anos completos |
| Espaço para o Brasil | 20% | Participação mundial do Brasil no produto − participação do Brasil no país |
| Abertura a fornecedores | 15% | 1 − HHI dos fornecedores concorrentes (excluindo o Brasil) |
| Presença brasileira | 10% | 100 se o Brasil tem ≥ 1% do mercado, 50 se < 1%, 0 se não fornece |

Cada indicador vira percentil entre os mercados avaliados. Se faltar algum, os pesos são
reescalados (`completeness_pct`). Mercados com menos de 0,05% das importações mundiais ficam fora
do ranking principal. A metodologia privilegia mercados **onde o Brasil ainda tem espaço para
crescer**; os pesos podem ser ajustados em `app/services/analysis.py`.

### Inteligência artificial

A IA **interpreta** os indicadores; ela não produz dados.

1. Recebe uma ficha de dados já calculada e um guia de leitura. Os prompts
   (`app/services/prompts.py`) proíbem números novos, nomes próprios fora da ficha e afirmações
   sobre tarifas, barreiras ou acordos, que só podem aparecer como "pontos a verificar".
2. **Conferência automática:** todo valor em US$ e % do texto gerado é comparado com os dados.
   O que não confere é destacado. NCMs inexistentes e mercados fora da lista são descartados.
3. Todo texto gerado é rotulado como **Estimativa**.

**Limitação:** a conferência valida números, não o raciocínio. Revise o texto antes de circular.

### Importar CSV do Comex Stat (opcional)

Baixe arquivos `EXP_AAAA.csv` em
[Base de dados bruta – MDIC](https://www.gov.br/mdic/pt-br/assuntos/comercio-exterior/estatisticas/base-de-dados-bruta),
coloque-os em `data\comexstat\` e execute:

```bash
venv\Scripts\python -m app.tools.comexstat_cli import                    # todos os EXP_*.csv da pasta
venv\Scripts\python -m app.tools.comexstat_cli import arquivo.csv --ncm 09   # só o capítulo 09
venv\Scripts\python -m app.tools.comexstat_cli sync                      # rebaixar tabelas NCM e países
```

---

## Configuração (`.env`)

| Variável | Uso |
|---|---|
| `APP_HOST`, `APP_PORT` | Endereço do servidor local (padrão `127.0.0.1:8000`) |
| `DATABASE_PATH` | Arquivo SQLite (padrão `data/cfi_market_finder.db`) |
| `COMTRADE_API_KEY` | Chave da UN Comtrade (`UNCOMTRADE_KEY` também é aceito) |
| `GROQ_API_KEY`, `GROQ_MODEL` | Inferência de IA via Groq (padrão `openai/gpt-oss-120b`) |

## Arquitetura

- **Backend:** Python 3.12+, FastAPI, Uvicorn, Pandas, SQLite (módulo `sqlite3`).
- **Frontend:** HTML, CSS e JavaScript puro (sem build), servido pelo próprio FastAPI;
  Plotly.js (gráficos) e Leaflet (mapa) copiados em `frontend/vendor/`.
- **Dados externos:** UN Comtrade, Comex Stat; **IA:** Groq.
- Todas as versões das dependências estão fixadas em `requirements.txt`.

```
CFI_market_finder/
├── run.bat / diagnostico.bat   Inicialização e diagnóstico no Windows
├── requirements.txt            Dependências (versões fixadas)
├── .env.example                Modelo de configuração (sem chaves reais)
├── app/                        Backend
│   ├── __main__.py             python -m app: porta, navegador, Uvicorn
│   ├── main.py                 Aplicação, rotas, tratamento de erros, frontend estático
│   ├── config.py / database.py Configuração (.env) e SQLite com migrações
│   ├── api/                    Rotas HTTP: health, searches, reference, trade, analysis, ai
│   ├── services/               Integrações e regras: comtrade, comexstat, reference,
│   │                           evolution, analysis, markets, ncm_ai, ai_insights, prompts…
│   └── tools/                  comexstat_cli (CSV/tabelas) e doctor (diagnóstico)
├── frontend/                   index.html, css/, js/ (ui, api, theme, charts, map,
│                               dashboard, report, app) e vendor/ (Plotly, Leaflet, mapa)
├── tests/                      Testes (pytest); test_live.py usa as APIs reais
└── data/                       Banco SQLite e CSVs (criado automaticamente, fora do git)
```

### API

A documentação interativa fica em <http://127.0.0.1:8000/docs>.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/health` | Status do banco, integrações e tabelas oficiais |
| GET | `/api/classify?q=` | Sugere NCMs para a descrição do produto (IA + tabela oficial) |
| GET | `/api/ncm/search?q=`, `/api/ncm/{código}` | Busca e consulta na tabela NCM oficial |
| GET/POST/DELETE | `/api/searches` | Pesquisas salvas |
| GET | `/api/trade/{código}/imports`, `/evolution` | Importadores e evolução histórica (Comtrade) |
| GET | `/api/brazil/{código}/exports` | Exportações brasileiras por ano e destino (Comex Stat) |
| GET | `/api/analysis/{código}/markets[/{ISO3}]` | Ranking de mercados e detalhe por país |
| GET | `/api/ai/{código}/markets/{ISO3}`, `/api/ai/{código}/report` | Análise e relatório com IA (`format=md` para baixar) |

As rotas de dados aceitam `refresh=true` para ignorar o cache.

## Cronograma

- [x] **Fase 1 — Fundação:** estrutura, ambiente Python, FastAPI, SQLite, frontend servido pelo FastAPI.
- [x] **Fase 2 — Integração de dados:** UN Comtrade, importações por país, evolução histórica,
      Comex Stat (API + CSV) e interpretação do produto → NCM com IA.
- [x] **Fase 3 — Motor de análise:** crescimento, fornecedores, participação brasileira,
      pontuação de atratividade e ranking.
- [x] **Fase 4 — Inteligência artificial:** prompts especializados, análises por país,
      recomendações e relatório executivo.
- [x] **Fase 5 — Interface:** painel, pesquisa, ranking, gráficos, mapa e relatório.
- [x] **Fase 6 — Testes e empacotamento:** testes reais e de falha, run.bat revisado,
      diagnóstico, dependências fixadas, README e teste de instalação do zero.

## Licenças de terceiros

Plotly.js (MIT), Leaflet (BSD-2-Clause) e fronteiras Natural Earth (domínio público);
detalhes em `frontend/vendor/LICENSES.md`.
