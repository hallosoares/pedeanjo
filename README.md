# 🇬🇧 UK100 DIGAO ORB Pre-Open Institutional Filter

Ferramenta de análise pré-abertura para a estratégia de **Opening Range Breakout (ORB)** no FTSE 100 (UK100).

Corre antes da abertura de Londres (~07:15 UK time), busca **dados reais de mercado**, calcula **6 módulos de scoring** (11 sinais independentes) e diz-te se o dia é favorável, se deves operar com cautela ou se é melhor ficar de fora.

---

## Instalação (Windows)

### Pré-requisitos (só uma vez)

1. **Git** — [Descarrega aqui](https://git-scm.com/download/win) → instala com as opções padrão
2. **Python 3.10+** — [Descarrega aqui](https://www.python.org/downloads/) → **IMPORTANTE: marca a checkbox "Add Python to PATH"** durante a instalação

### Instalar (copy-paste no PowerShell)

Abre o **PowerShell** (clica direito no botão Windows → "Terminal" ou "PowerShell") e cola isto tudo de uma vez:

```powershell
cd "$HOME\Desktop"; git clone https://github.com/hallosoares/pedeanjo.git; cd pedeanjo; python -m venv venv; venv\Scripts\pip install -r requirements.txt; copy pedeanjo_go.bat "$HOME\Desktop\pedeanjo_go.bat"; venv\Scripts\python uk100_orb_filter.py
```

Isto vai:
- ✅ Criar a pasta `pedeanjo` no teu Desktop
- ✅ Instalar tudo automaticamente
- ✅ Copiar o atalho `pedeanjo_go.bat` para o Desktop
- ✅ Correr a primeira análise

### Usar todos os dias

**Opção A** — Faz duplo-clique em `pedeanjo_go.bat` no Desktop.

**Opção B** — Abre o PowerShell e escreve:

```powershell
cd "$HOME\Desktop\pedeanjo"; venv\Scripts\python uk100_orb_filter.py
```

---

## Instalação (Linux / macOS)

```bash
cd ~/Desktop && git clone https://github.com/hallosoares/pedeanjo.git && cd pedeanjo && python3 -m venv venv && venv/bin/pip install -r requirements.txt && chmod +x pedeanjo_go && mkdir -p ~/.local/bin && ln -sf "$(pwd)/pedeanjo_go" ~/.local/bin/pedeanjo_go && echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc && pedeanjo_go
```

Depois é só escrever `pedeanjo_go` em qualquer terminal.

---

## Opções

```
pedeanjo_go                  # Análise completa (usa isto todos os dias)
pedeanjo_go --json           # Output em JSON
pedeanjo_go --history        # Ver últimas 10 análises
pedeanjo_go --history 20     # Ver últimas 20 análises
pedeanjo_go --raw            # Mostra raw data (debug)
```

---

##  O que analisa

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
| 10-14 |  **DIA FAVORÁVEL** | Operar ORB com confiança |
| 6-9 |  **OPERAR COM CAUTELA** | Reduzir tamanho, stops mais apertados |
| 0-5 |  **NÃO OPERAR** | Ficar de fora |

---

##  Output de exemplo

```
================================================================
   UK100 ORB PRE-OPEN INSTITUTIONAL FILTER
   Thursday, 02 April 2026 — 07:15:02 (local)
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

##  11 Sinais em Tempo Real

Todos os dados são buscados **ao vivo** (yfinance + ForexFactory). Sem API keys. Sem custos.

| Sinal | Fonte |
|-------|-------|
| S&P 500 futures, DAX, Euro Stoxx 50 | Sentimento global antes do FTSE abrir |
| Nikkei 225, Hang Seng | Sessão asiática — driver do gap de abertura |
| Crude Oil, Gold, GBP/USD | Correlações macro — confirmam direção |
| ATR + Bollinger Squeeze | Regime de volatilidade — expansão vs compressão |
| VIX + VIX Term Structure | Nível de medo + contango vs backwardation |
| RSI 14 dias FTSE | Sobrecomprado/sobrevendido antes do open |
| Volume FTSE | Spike institucional vs volume seco |
| Yield Curve US 2Y/10Y | Inversão = sinal de recessão |
| Divergência Intermercados | FTSE vs DAX/SPX — deteta dislocações |
| Sazonalidade | Padrões ORB por dia da semana |
| Força GBP vs basket | GBP vs USD, JPY, CHF, EUR |

