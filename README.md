# UK100 ORB Pre-Open Institutional Filter

Ferramenta profissional de filtragem pré-abertura para a estratégia de **Opening Range Breakout (ORB)** no FTSE 100 (UK100).

Corre antes da abertura de Londres (~07:15 UK time), busca dados reais de mercado, calcula 5 módulos de scoring e diz-te se o dia é favorável, se deves operar com cautela ou se é melhor não operar.

---

## O que esse treco faz ??

- Busca **dados reais em tempo real** (10 tickers: S&P 500 futures, DAX, Euro Stoxx 50, Crude Oil, Gold, GBP/USD, FTSE 100, VIX, **Nikkei 225, Hang Seng**)
- Busca o **calendário económico ForexFactory** (notícias de alto/médio impacto — GBP, USD, EUR)
- Calcula **ATR volatility regime** + **Bollinger Squeeze** (Bollinger Bands dentro de Keltner Channels)
- Analisa o **VIX** (medo de mercado) para contexto de volatilidade
- Calcula o **RSI 14 dias do FTSE** — deteta sobrecomprado/sobrevendido antes do open
- Avalia a **sessão asiática** (Nikkei + Hang Seng) — o principal driver do gap de abertura do FTSE
- Avalia **5 módulos** (0-11 pontos):
  1. **Eventos Macro** (0-3) — notícias de alto impacto perto da abertura?
  2. **Sentimento Global** (0-2) — futuros alinhados + sessão asiática?
  3. **Correlações** (0-2) — Oil, Gold, GBP/USD coerentes?
  4. **Volatilidade** (0-2) — ATR + VIX + BB Squeeze + volume + RSI
  5. **Estrutura Pré-Abertura** (0-2) — mercado esticado ou limpo?
- Classifica: **DIA FAVORÁVEL** (8-11) / **OPERAR COM CAUTELA** (5-7) / **NÃO OPERAR** (0-4)
- Indica **direção**: COMPRADO / VENDIDO / NÃO OPERAR
- **Regista cada análise** em `analysis_log.jsonl` — rastreia a precisão ao longo do tempo
- Tudo em **Português**, formato institucional

---

## Instalação (1 minuto)

```bash
# 1. Clonar o repositório
git clone <URL_DO_REPO> pedeanjo
cd pedeanjo

# 2. Criar virtual environment e instalar dependências
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. (Opcional) Criar atalho global — corre de qualquer pasta
mkdir -p ~/.local/bin
ln -sf "$(pwd)/pedeanjo_go" ~/.local/bin/pedeanjo_go
# Certifica-te que ~/.local/bin está no teu PATH
```

Requisitos: **Python 3.10+** (testado com 3.12). Funciona em Linux, macOS e Windows (WSL).

---

## Como usar

```bash
# Análise completa
python uk100_orb_filter.py

# Ou com o atalho (de qualquer pasta):
pedeanjo_go

# Mostrar raw data para debug
pedeanjo_go --raw

# Output em JSON (para integração com outros tools)
pedeanjo_go --json

# Ver histórico das últimas 10 análises
pedeanjo_go --history

# Ver histórico das últimas 20 análises
pedeanjo_go --history 20
```

### Output de exemplo

```
================================================================
   UK100 ORB PRE-OPEN INSTITUTIONAL FILTER
   Wednesday, 01 April 2026 — 07:15:02 (local)
================================================================

  1. EVENTOS E RISCO MACRO
    Score: 3/3  [###]
    Dia limpo. Sem eventos de alto impacto relevantes.

  2. SENTIMENTO GLOBAL
    Score: 2/2  [##]
    Forte risk-on global. SPX: +0.65%, DAX: +0.80%, STOXX50: +0.72%

  3. CORRELAÇÕES CHAVE
    Score: 2/2  [##]
    Alinhamento claro com direção do índice (bullish). Oil: +0.40%, Gold: -0.20%, GBP/USD: +0.35%

  4. CONDIÇÃO DE VOLATILIDADE
    Score: 2/2  [##]
    Condições ideais: expansão ATR + VIX em zona ótima (18.5).

  5. ESTRUTURA PRÉ-ABERTURA
    Score: 2/2  [##]
    Bem posicionado para rompimento limpo. FTSE gap: +0.25%

----------------------------------------------------------------

   Score: 11/11
   Classificação: DIA FAVORÁVEL
   Direção: COMPRADO (Long)
================================================================
```

---

## Porquê esta ferramenta em vez de colar o prompt no ChatGPT?

| | Esta ferramenta | Colar prompt no ChatGPT/Grok |
|---|---|---|
| **Dados** | Busca dados REAIS em tempo real (yfinance + ForexFactory) | O LLM não tem acesso a dados live — inventa ou usa dados antigos |
| **VIX** | Valor actual do VIX com análise de zona (15-25 ideal, >30 perigo) | O LLM não sabe o VIX de hoje |
| **RSI FTSE** | RSI 14 dias calculado — sobrecomprado/sobrevendido antes do open | O LLM não tem acesso a dados históricos de preço |
| **Sessão Asiática** | Nikkei + Hang Seng overnight — driver real do gap de abertura do FTSE | O LLM não sabe o que aconteceu esta noite no Japão/HK |
| **Volume FTSE** | Ratio volume/média 5 dias — detecta spike institucional ou volume seco | O LLM não tem acesso a dados de volume |
| **Tendência multi-day** | 5-10 dias de closes reais, consistência e momentum calculados | O LLM "adivinha" a tendência |
| **Volatilidade** | ATR calculado + Bollinger Squeeze real | O LLM "adivinha" se há volatilidade |
| **Calendário** | ForexFactory com impacto, hora, país — filtrado automaticamente | O LLM pode alucinar eventos que não existem |
| **Consistência** | Regras fixas, mesmo input = mesmo output | O LLM dá respostas diferentes cada vez |
| **Velocidade** | ~10 segundos | Abrir browser, colar prompt, esperar... |
| **Histórico** | `analysis_log.jsonl` — regista cada análise para validar precisão | O LLM não tem memória de sessões anteriores |

---

## Estrutura do Projeto

```
pedeanjo/
  uk100_orb_filter.py   # Ferramenta principal (~1400 linhas)
  pedeanjo_go            # Shell launcher (funciona de qualquer pasta)
  requirements.txt       # Dependências Python
  analysis_log.jsonl     # Histórico de análises (auto-gerado)
  .gitignore
  README.md
```

---

## Licença

Uso pessoal / interno. Desenvolvido por fesimon.
