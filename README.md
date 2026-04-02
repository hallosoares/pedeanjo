# 🇬🇧 UK100 ORB Pre-Open Institutional Filter

Ferramenta de análise pré-abertura para a estratégia de **Opening Range Breakout (ORB)** no FTSE 100 (UK100).

Corre antes da abertura de Londres (~07:15 UK time), busca **dados reais de mercado**, calcula **6 módulos de scoring** (11 sinais independentes) e diz-te se o dia é favorável, se deves operar com cautela ou se é melhor ficar de fora.

---

## ⚡ Instalação Rápida (copy-paste no terminal)

> **Requisitos:** Python 3.10+ e Git. Funciona em Linux, macOS e Windows (WSL).

### 1. Clonar e instalar

```bash
git clone https://github.com/hallosoares/pedeanjo.git
cd pedeanjo
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Criar o comando `pedeanjo_go` (funciona de qualquer pasta)

```bash
chmod +x pedeanjo_go
mkdir -p ~/.local/bin
ln -sf "$(pwd)/pedeanjo_go" ~/.local/bin/pedeanjo_go
```

Se `~/.local/bin` não estiver no teu PATH, adiciona esta linha ao teu `~/.bashrc` (ou `~/.zshrc`):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### 3. Testar

```bash
pedeanjo_go
```

É só isto. A partir de agora, abres o terminal e escreves `pedeanjo_go` antes da abertura de Londres.

---

## 🚀 Como usar

```bash
pedeanjo_go                  # Análise completa (usa isto todos os dias)
pedeanjo_go --json           # Output em JSON (para integração com outros tools)
pedeanjo_go --history        # Ver histórico das últimas 10 análises
pedeanjo_go --history 20     # Ver histórico das últimas 20 análises
pedeanjo_go --raw            # Mostra raw data no final (debug)
```

Ou, se preferires correr diretamente sem o atalho:

```bash
cd pedeanjo
venv/bin/python uk100_orb_filter.py
```

---

## 📊 O que analisa

| # | Módulo | Pontos | O que faz |
|---|--------|--------|-----------|
| 1 | **Eventos Macro** | 0-3 | ForexFactory: notícias de alto impacto perto da abertura? |
| 2 | **Sentimento Global** | 0-2 | SPX futures, DAX, Euro Stoxx 50 + sessão asiática (Nikkei, Hang Seng) |
| 3 | **Correlações** | 0-2 | Oil, Gold, GBP/USD — coerentes com direção do FTSE? |
| 4 | **Volatilidade** | 0-2 | ATR regime + Bollinger Squeeze + VIX + Volume + RSI 14d |
| 5 | **Estrutura Pré-Abertura** | 0-2 | Mercado esticado ou limpo? + tendência multi-day |
| 6 | **Sinais Avançados** | 0-3 | VIX term structure + yield curve + divergência + sazonalidade + força GBP |
| | **TOTAL** | **0-14** | |

### Classificação

| Score | Classificação | O que fazer |
|-------|--------------|-------------|
| 10-14 | 🟢 **DIA FAVORÁVEL** | Operar ORB com confiança |
| 6-9 | 🟡 **OPERAR COM CAUTELA** | Reduzir tamanho, stops mais apertados |
| 0-5 | 🔴 **NÃO OPERAR** | Ficar de fora |

---

## 📋 Output de exemplo

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
    Alinhamento claro com direção do índice (bullish).

  4. CONDIÇÃO DE VOLATILIDADE
    Score: 2/2  [##]
    Condições ideais: expansão ATR + VIX em zona ótima (18.5).

  5. ESTRUTURA PRÉ-ABERTURA
    Score: 2/2  [##]
    Bem posicionado para rompimento limpo. FTSE gap: +0.25%

  6. SINAIS AVANÇADOS
    Score: 3/3  [###]
    Forte alinhamento de sinais avançados (+4).

----------------------------------------------------------------

   Score: 14/14
   Classificação: DIA FAVORÁVEL
   Direção: COMPRADO (Long)
================================================================
```

---

## 📡 11 Sinais em Tempo Real

Todos os dados são buscados **ao vivo** (yfinance + ForexFactory). Sem API keys. Sem custos.

| Sinal | Fonte | Porquê |
|-------|-------|--------|
| S&P 500 futures, DAX, Euro Stoxx 50 | yfinance | Sentimento global antes do FTSE abrir |
| Nikkei 225, Hang Seng | yfinance | Sessão asiática — driver do gap de abertura |
| Crude Oil, Gold, GBP/USD | yfinance | Correlações macro — confirmam direção |
| ATR + Bollinger Squeeze | Calculado | Regime de volatilidade — expansão vs compressão |
| VIX | yfinance | Nível de medo — 15-25 ideal, >30 perigo |
| RSI 14 dias FTSE | Calculado | Sobrecomprado/sobrevendido antes do open |
| Volume FTSE | yfinance | Spike institucional vs volume seco |
| VIX Term Structure | yfinance (^VIX vs ^VIX3M) | Contango (calmo) vs backwardation (pânico) |
| Yield Curve US 2Y/10Y | yfinance (^TNX vs 2YY=F) | Inversão = sinal de recessão |
| Divergência Intermercados | Calculado (FTSE vs DAX/SPX) | Deteta dislocações multi-day |
| Sazonalidade + Força GBP | Calculado | Dia da semana + GBP vs basket (USD, JPY, CHF, EUR) |

---

## 🆚 Porquê isto em vez de perguntar ao ChatGPT?

| | Esta ferramenta | Perguntar ao ChatGPT/Grok |
|---|---|---|
| **Dados** | Busca dados REAIS em tempo real | O LLM inventa ou usa dados antigos |
| **VIX** | Valor actual com análise de zona | Não sabe o VIX de hoje |
| **Sessão Asiática** | Nikkei + HSI overnight reais | Não sabe o que aconteceu esta noite |
| **Calendário** | ForexFactory com impacto e hora | Pode alucinar eventos |
| **Consistência** | Mesmas regras, mesmo input = mesmo output | Respostas diferentes cada vez |
| **Velocidade** | ~15 segundos | Abrir browser, colar prompt, esperar... |
| **Histórico** | `analysis_log.jsonl` regista tudo | Sem memória de sessões anteriores |

---

## 📁 Estrutura do Projeto

```
pedeanjo/
  uk100_orb_filter.py        # Ferramenta principal (6 módulos de scoring)
  signals/                   # Sinais avançados (módulos independentes)
    __init__.py
    vix_term_structure.py    # VIX contango/backwardation
    bond_yield_curve.py      # US 2Y/10Y spread
    intermarket_divergence.py # FTSE vs DAX/SPX divergência
    seasonality.py           # Padrões ORB por dia da semana
    currency_strength.py     # GBP vs basket (USD, JPY, CHF, EUR)
  pedeanjo_go                # Shell launcher (funciona de qualquer pasta)
  requirements.txt           # Dependências Python
  analysis_log.jsonl         # Histórico de análises (auto-gerado)
  README.md
```

---

## 🔄 Actualizar

Quando houver uma versão nova:

```bash
cd pedeanjo
git pull
venv/bin/pip install -r requirements.txt
```

---

## Licença

Uso pessoal / interno. Desenvolvido por fesimon.
