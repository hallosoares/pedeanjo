#!/usr/bin/env python3
"""
UK100 ORB Pre-Open Institutional Filter
=========================================================
Run this before the London open (~07:15 UK time) to get a scored
pre-open analysis for the FTSE 100 Opening Range Breakout strategy.

Usage:
    python uk100_orb_filter.py                    # rule-based (instant)
    python uk100_orb_filter.py --raw              # also print raw fetched data
    python uk100_orb_filter.py --json             # output as JSON
    python uk100_orb_filter.py --help             # show help

    # Optional (requires Ollama installed locally — see README):
    python uk100_orb_filter.py --ollama           # LLM institutional analysis
    python uk100_orb_filter.py --ollama --model mistral:7b-instruct-q4_K_M

Modes:
    Default   : Rule-based scoring (fast, deterministic, ~10 seconds)
                Fetches REAL live data, scores 5 modules, outputs in Portuguese.
                This is the main mode — no extra software needed.
    --ollama  : (OPTIONAL) Sends the same real data to a local Ollama LLM for
                a narrative institutional analysis. Requires Ollama installed.

Data sources (all free, no API keys):
    - yfinance   : Futures, FX, FTSE prices, ATR/volatility, VIX
    - ForexFactory (faireconomy.media) : Economic calendar with impact levels
    - pandas_ta  : Bollinger Bands / Keltner Channel squeeze detection
    - Ollama (OPTIONAL, local LLM) : Institutional-grade narrative in Portuguese

Author : fesimon (pedeanjo)
Version: 3.0.0 (CLI — rule-based + Ollama LLM scoring + VIX + BB squeeze)
"""

import argparse
import json
import re
import sys
import time as _time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yfinance as yf

try:
    import ollama as _ollama_lib
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# Countries we care about for macro events
RELEVANT_COUNTRIES = {"GBP", "USD", "EUR"}

# Hours window around London open (08:00 UK) to flag events as "near open"
# We check events from 06:00 to 10:00 UK time
EVENT_WINDOW_BEFORE_OPEN_H = 2  # 06:00
EVENT_WINDOW_AFTER_OPEN_H = 2   # 10:00

# Tickers for futures & correlations
TICKERS = {
    "SPX_futures": "ES=F",       # S&P 500 E-mini futures
    "DAX":         "^GDAXI",     # DAX index
    "STOXX50":     "^STOXX50E",  # Euro Stoxx 50
    "OIL":         "CL=F",       # WTI Crude Oil futures
    "GOLD":        "GC=F",       # Gold futures
    "GBPUSD":      "GBPUSD=X",   # GBP/USD spot
    "FTSE":        "^FTSE",      # FTSE 100 index
    "VIX":         "^VIX",       # CBOE Volatility Index
}

# ForexFactory calendar URL (free, no key)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# ATR parameters
ATR_PERIOD = 14
HISTORY_DAYS = "1mo"  # enough for ATR calculation

# Calendar cache — avoids 429 rate-limit on repeated runs
CALENDAR_CACHE_FILE = Path(__file__).parent / ".calendar_cache.json"
CALENDAR_CACHE_TTL_MIN = 30  # minutes

# Default Ollama model (can be overridden with --model)
DEFAULT_OLLAMA_MODEL = "llama3.1:8b"

# ---------------------------------------------------------------------------
# BROTHER'S EXACT PROMPT (Portuguese — institutional trader tone)
# ---------------------------------------------------------------------------

BROTHER_PROMPT = """Atue como um trader institucional especialista em índices europeus, com foco no FTSE 100 Index (UK100), combinando macroeconomia, fluxo global e correlações intermarket.

Preciso que você avalie o cenário de HOJE poucos minutos antes da abertura da sessão de Londres para validar se minha estratégia de opening range breakout (M5, primeiros 20 minutos) tem probabilidade de continuidade ou risco elevado de fakeout.

⚠️ Seu objetivo principal é FILTRAR o dia — não é forçar trade.

1. EVENTOS E RISCO MACRO (0–2 pontos)
Há notícias de alto impacto hoje? (United Kingdom, United States, Eurozone)
Estão próximas da abertura de Londres?

Pontuação: 0 = Alto risco / notícias iminentes → EVITAR operar
1 = Risco moderado
2 = Dia limpo / sem eventos relevantes

2. SENTIMENTO GLOBAL (0–2 pontos)
Analise: S&P 500 (futuros), DAX, Euro Stoxx 50

Pontuação: 0 = Indefinido / lateral / divergente
1 = Leve viés
2 = Forte risk-on ou risk-off (alinhado)

3. CORRELAÇÕES CHAVE (0–2 pontos)
Avalie direção e coerência: Crude Oil, GBP/USD, Gold

Pontuação: 0 = Confuso / divergente
1 = Parcialmente alinhado
2 = Alinhamento claro com direção do índice

4. CONDIÇÃO DE VOLATILIDADE (0–2 pontos)
Ambiente favorece expansão (bom para breakout)? Ou compressão / manipulação (propenso a fakeout)?

Pontuação: 0 = Baixa qualidade (fakeouts prováveis)
1 = Médio
2 = Alta probabilidade de expansão

5. ESTRUTURA PRÉ-ABERTURA (0–2 pontos)
Mercado já está estendido antes da abertura? Ou bem posicionado para gerar movimento novo?

Pontuação: 0 = Esticado / exausto
1 = Neutro
2 = Bem posicionado para rompimento limpo

🔢 SCORE FINAL (0–10)
Some tudo e classifique:
0–3 → ❌ NÃO OPERAR (alto risco de fakeout)
4–6 → ⚠️ OPERAR COM CAUTELA (reduzir risco)
7–10 → ✅ DIA FAVORÁVEL (buscar rompimento)

🎯 DIREÇÃO (OBRIGATÓRIO)
Escolha apenas UMA: COMPRADO / VENDIDO / NÃO OPERAR

📊 RESPOSTA FINAL (FORMATO FIXO — OBRIGATÓRIO seguir exatamente)
Score: X/10
Classificação: (Não operar / Cautela / Favorável)
Direção: (Comprado / Vendido / Não operar)

Resumo (máx. 5 linhas):
(Apenas o essencial que justifica a decisão)

⚠️ Regras importantes:
- Seja direto e objetivo (nível mesa institucional)
- Evite respostas neutras
- Se houver notícia relevante próxima → priorize NÃO OPERAR
- Foque em evitar fakeouts, não em gerar trades"""


# ---------------------------------------------------------------------------
# OLLAMA LLM INTEGRATION
# ---------------------------------------------------------------------------

def _build_data_block(calendar_data: dict, market_data: dict,
                      vol_data: dict, structure_data: dict) -> str:
    """
    Build a clean, structured text block of ALL real fetched data
    to inject into the LLM prompt.  No fake data, no placeholders.
    """
    lines = []
    now = datetime.now()
    lines.append(f"Data/Hora: {now.strftime('%A, %d %B %Y — %H:%M UTC')}")
    lines.append("")

    # --- Calendar events ---
    lines.append("=== CALENDÁRIO ECONÓMICO (dados reais ForexFactory) ===")
    if calendar_data.get("calendar_unavailable"):
        lines.append("Calendário indisponível no momento.")
    else:
        if calendar_data["has_near_open_high"]:
            lines.append("EVENTOS DE ALTO IMPACTO PERTO DA ABERTURA DE LONDRES:")
            for ev in calendar_data["near_open_high_impact"]:
                lines.append(f"  • {ev['time_utc']} — {ev['title']} ({ev['country']})")
                if ev.get('forecast'):
                    lines.append(f"    Forecast: {ev['forecast']}  |  Previous: {ev.get('previous', 'N/A')}")
        elif calendar_data["has_high_impact"]:
            lines.append("Eventos de alto impacto hoje (mas FORA da janela de abertura):")
            for ev in calendar_data["high_impact_events"]:
                lines.append(f"  • {ev['time_utc']} — {ev['title']} ({ev['country']})")
        else:
            lines.append(f"Sem eventos de alto impacto. {calendar_data['total_medium']} eventos de médio impacto.")

        if calendar_data.get("medium_impact_events"):
            lines.append(f"\nEventos de médio impacto ({calendar_data['total_medium']}):")
            for ev in calendar_data["medium_impact_events"][:5]:
                lines.append(f"  • {ev['time_utc']} — {ev['title']} ({ev['country']})")
    lines.append("")

    # --- Market data ---
    lines.append("=== DADOS DE MERCADO (preços reais yfinance) ===")
    display_names = {
        "SPX_futures": "S&P 500 Futures (ES=F)",
        "DAX": "DAX (^GDAXI)",
        "STOXX50": "Euro Stoxx 50 (^STOXX50E)",
        "OIL": "Crude Oil WTI (CL=F)",
        "GOLD": "Gold (GC=F)",
        "GBPUSD": "GBP/USD",
        "FTSE": "FTSE 100 (^FTSE)",
        "VIX": "CBOE VIX (^VIX)",
    }
    for name in ["SPX_futures", "DAX", "STOXX50", "OIL", "GOLD", "GBPUSD", "FTSE", "VIX"]:
        data = market_data.get(name, {})
        pct = data.get("pct_change")
        last = data.get("last_close")
        label = display_names.get(name, name)
        if pct is not None and last is not None:
            arrow = "+" if pct > 0 else ("-" if pct < 0 else "=")
            lines.append(f"  {label}: {last:.2f}  {arrow} {pct:+.2f}%")
        else:
            lines.append(f"  {label}: dados indisponíveis")
    lines.append("")

    # --- Volatility ---
    lines.append("=== VOLATILIDADE FTSE 100 ===")
    regime = vol_data.get("vol_regime", "unknown")
    atr = vol_data.get("current_atr", "N/A")
    avg = vol_data.get("avg_atr", "N/A")
    ratio = vol_data.get("atr_ratio", "N/A")
    lines.append(f"  Regime: {regime}")
    lines.append(f"  ATR atual: {atr}  |  ATR médio: {avg}  |  Ratio: {ratio}")
    if regime == "expansion":
        lines.append("  → Ambiente favorece expansão/breakout.")
    elif regime == "compression":
        lines.append("  → Compressão detectada — cuidado com fakeouts.")
    # VIX
    vix_data = market_data.get("VIX", {})
    vix_last = vix_data.get("last_close")
    if vix_last is not None:
        lines.append(f"  VIX: {vix_last:.2f}")
        if vix_last > 25:
            lines.append("  → VIX elevado — alta volatilidade implícita, ranges amplos mas mais fakeouts.")
        elif vix_last < 15:
            lines.append("  → VIX baixo — mercado complacente, ranges apertados, ORB mais difícil.")
        else:
            lines.append("  → VIX em zona ótima para ORB (15-25).")
    # Bollinger Squeeze
    bb_squeeze = vol_data.get("bb_squeeze")
    if bb_squeeze is not None:
        if bb_squeeze:
            lines.append("  Bollinger Squeeze ATIVO — compressão extrema, breakout iminente.")
        else:
            lines.append("  Sem squeeze ativo.")
    lines.append("")

    # --- Pre-open structure ---
    lines.append("=== ESTRUTURA PRÉ-ABERTURA ===")
    if structure_data.get("is_extended"):
        moves = ", ".join(structure_data.get("big_moves", []))
        lines.append(f"   Mercado ESTICADO antes da abertura. Movimentos grandes: {moves}")
    else:
        ftse_gap = structure_data.get("ftse_gap_pct")
        if ftse_gap is not None:
            lines.append(f"  Estrutura limpa. FTSE gap: {ftse_gap:+.2f}%")
        else:
            lines.append("  Estrutura neutra. Gap não disponível.")
    lines.append("")

    return "\n".join(lines)


def ollama_scoring(calendar_data: dict, market_data: dict,
                   vol_data: dict, structure_data: dict,
                   model: str = DEFAULT_OLLAMA_MODEL) -> dict | None:
    """
    Send REAL live data + brother's exact prompt to local Ollama.
    Parses the LLM response to extract Score, Classificação, Direção, Resumo.
    Returns dict with all parsed fields + the full raw LLM response.
    """
    if not OLLAMA_AVAILABLE:
        print("   Pacote 'ollama' não instalado. Execute: pip install ollama")
        return None

    data_block = _build_data_block(calendar_data, market_data, vol_data, structure_data)

    full_message = (
        f"{BROTHER_PROMPT}\n\n"
        f"\n"
        f"DADOS BRUTOS ATUALIZADOS (reais, coletados agora, Londres pre-open):\n"
        f"\n\n"
        f"{data_block}\n\n"
        f"Com base EXCLUSIVAMENTE nos dados acima, forneça sua análise "
        f"no FORMATO FIXO exigido. Seja preciso e institucional."
    )

    print(f"  A enviar dados reais para Ollama ({model})...")
    print(f"  Isto pode demorar 30-90 segundos dependendo do modelo...")

    start_time = _time_module.time()
    try:
        response = _ollama_lib.chat(
            model=model,
            messages=[{"role": "user", "content": full_message}],
            options={
                "temperature": 0.3,      # Low temp for precise output
                "num_predict": 1024,     # Enough for the full response
                "top_p": 0.9,
            },
        )
        elapsed = _time_module.time() - start_time
        content = response.message.content
        print(f"   Resposta recebida em {elapsed:.1f}s")
    except Exception as e:
        print(f"   Erro Ollama: {e}")
        print(f"   Verifique se o servidor Ollama está rodando (ollama serve)")
        print(f"   Verifique se o modelo está instalado (ollama pull {model})")
        return None

    result = _parse_ollama_response(content)
    result["raw_llm_response"] = content
    result["model"] = model
    result["response_time_s"] = round(elapsed, 1)
    return result


def _parse_ollama_response(content: str) -> dict:
    """
    Parse the LLM's response to extract Score, Classificação, Direção, Resumo.
    Handles variations in formatting gracefully.
    """
    result = {
        "score": None,
        "classification": None,
        "direction": None,
        "summary": None,
    }

    lines = content.strip().split("\n")

    for line in lines:
        line_clean = line.strip()
        # Strip markdown bold markers
        line_clean = re.sub(r'\*\*', '', line_clean)

        # Score: X/10
        if result["score"] is None:
            score_match = re.search(r'[Ss]core[:\s]+\s*(\d{1,2})\s*/\s*10', line_clean)
            if score_match:
                result["score"] = int(score_match.group(1))

        # Classificação
        if result["classification"] is None:
            class_match = re.search(
                r'[Cc]lassifica[çc][ãa]o[:\s]+\s*(.+)',
                line_clean
            )
            if class_match:
                raw_class = class_match.group(1).strip()
                raw_lower = raw_class.lower()
                if "não operar" in raw_lower or "nao operar" in raw_lower:
                    result["classification"] = "NÃO OPERAR"
                elif "cautela" in raw_lower:
                    result["classification"] = "OPERAR COM CAUTELA"
                elif "favorável" in raw_lower or "favoravel" in raw_lower:
                    result["classification"] = "DIA FAVORÁVEL"
                else:
                    result["classification"] = raw_class

        # Direção
        if result["direction"] is None:
            dir_match = re.search(
                r'[Dd]ire[çc][ãa]o[:\s]+\s*(.+)',
                line_clean
            )
            if dir_match:
                raw_dir = dir_match.group(1).strip()
                raw_dir_lower = raw_dir.lower()
                if "comprado" in raw_dir_lower:
                    result["direction"] = "COMPRADO"
                elif "vendido" in raw_dir_lower:
                    result["direction"] = "VENDIDO"
                elif "não operar" in raw_dir_lower or "nao operar" in raw_dir_lower:
                    result["direction"] = "NÃO OPERAR"
                else:
                    result["direction"] = raw_dir.upper()

    # Extract Resumo — everything after "Resumo" line
    resumo_lines = []
    in_resumo = False
    for line in lines:
        line_clean = line.strip()
        # Strip markdown bold markers for matching
        line_stripped = re.sub(r'\*\*', '', line_clean).strip()
        if re.search(r'[Rr]esumo', line_stripped) and not in_resumo:
            in_resumo = True
            after = re.sub(r'.*[Rr]esumo[^:]*:\s*', '', line_stripped)
            if after and after != line_stripped:
                resumo_lines.append(after)
            continue
        if in_resumo and line_stripped:
            if re.match(r'^(Score|Classifica|Dire[çc]|Justificativa)', line_stripped):
                break
            # Skip lines that are just the prompt's rules echoed back
            if re.match(r'^(Regras|Seja direto|Evite respostas|Se houver|Foque em)', line_stripped):
                break
            # Strip leading bullet chars and markdown bold markers
            cleaned = re.sub(r'^[-•*]\s*', '', line_stripped)
            cleaned = cleaned.strip()
            if cleaned:
                resumo_lines.append(cleaned)

    if resumo_lines:
        result["summary"] = "\n".join(resumo_lines[:5])

    # Fallback: if score parsing failed, try broader pattern
    if result["score"] is None:
        score_match = re.search(r'(\d{1,2})\s*/\s*10', content)
        if score_match:
            result["score"] = int(score_match.group(1))

    return result


def print_ollama_output(ollama_result: dict, calendar_data: dict,
                        market_data: dict, vol_data: dict,
                        structure_data: dict, show_raw: bool = False):
    """
    Print the Ollama analysis in a beautiful terminal format.
    """
    now = datetime.now()

    print()
    print("=" * 64)
    print("   UK100 ORB PRE-OPEN INSTITUTIONAL FILTER")
    print(f"   {now.strftime('%A, %d %B %Y')} — {now.strftime('%H:%M:%S')} (local)")
    print(f"   Powered by Ollama ({ollama_result.get('model', '?')})")
    print(f"   Response time: {ollama_result.get('response_time_s', '?')}s")
    print("=" * 64)
    print()

    score = ollama_result.get("score", "?")
    classification = ollama_result.get("classification", "?")
    direction = ollama_result.get("direction", "?")
    summary = ollama_result.get("summary", "(sem resumo)")

    print(f"   Score: {score}/11")
    print(f"   Classificação: {classification}")
    print(f"   Direção: {direction}")
    print()
    print("   Resumo:")
    if summary:
        for line in summary.split("\n"):
            print(f"     - {line}")
    print()
    print("-" * 64)

    # Market snapshot
    print()
    print("   SNAPSHOT DOS MERCADOS (dados reais):")
    display_names = {
        "SPX_futures": "S&P 500 fut",
        "DAX": "DAX",
        "STOXX50": "Euro Stoxx",
        "OIL": "Crude Oil",
        "GOLD": "Gold",
        "GBPUSD": "GBP/USD",
        "FTSE": "FTSE 100",
        "VIX": "VIX",
    }
    for name in ["SPX_futures", "DAX", "STOXX50", "OIL", "GOLD", "GBPUSD", "FTSE", "VIX"]:
        data = market_data.get(name, {})
        pct = data.get("pct_change")
        last = data.get("last_close")
        label = display_names.get(name, name)
        if pct is not None and last is not None:
            arrow = "+" if pct > 0 else ("-" if pct < 0 else "=")
            print(f"    {label:>12s}: {last:>10.2f}  {arrow} {pct:+.2f}%")
        else:
            print(f"    {label:>12s}: dados indisponíveis")

    # Volatility
    print()
    regime = vol_data.get("vol_regime", "?")
    atr = vol_data.get("current_atr", "?")
    avg = vol_data.get("avg_atr", "?")
    ratio = vol_data.get("atr_ratio", "?")
    print(f"   Volatilidade: {regime} (ATR: {atr}, Média: {avg}, Ratio: {ratio})")
    bb_squeeze = vol_data.get("bb_squeeze")
    if bb_squeeze is True:
        print("   Bollinger Squeeze ATIVO — breakout iminente.")

    # Calendar highlights
    if calendar_data.get("near_open_high_impact"):
        print()
        print("   ALERTAS DE CALENDÁRIO (alto impacto perto da abertura):")
        for ev in calendar_data["near_open_high_impact"]:
            print(f"    • {ev['time_utc']} — {ev['title']} ({ev['country']})")

    if calendar_data.get("high_impact_events"):
        remaining = [
            e for e in calendar_data["high_impact_events"]
            if e not in calendar_data.get("near_open_high_impact", [])
        ]
        if remaining:
            print()
            print("   Outros eventos de alto impacto hoje:")
            for ev in remaining:
                print(f"    • {ev['time_utc']} — {ev['title']} ({ev['country']})")

    print()
    print("=" * 64)
    print()

    if show_raw:
        print("\n--- RAW LLM RESPONSE ---")
        print(ollama_result.get("raw_llm_response", ""))
        print("--- END RAW LLM RESPONSE ---\n")


# ---------------------------------------------------------------------------
# DATA FETCHING
# ---------------------------------------------------------------------------

def fetch_economic_calendar() -> list[dict]:
    """
    Fetch this week's economic calendar from ForexFactory (faireconomy.media).
    Returns list of events with: title, country, date, impact, forecast, previous.
    Uses a local file cache (30-min TTL) to avoid 429 rate-limit on repeated runs.
    Falls back to cache if API fails.  Retries up to 4 times with jitter.
    """
    import random
    import time as _time

    # --- Try cache first ---
    if CALENDAR_CACHE_FILE.exists():
        try:
            cache_age_min = (_time_module.time() - CALENDAR_CACHE_FILE.stat().st_mtime) / 60
            if cache_age_min < CALENDAR_CACHE_TTL_MIN:
                with open(CALENDAR_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, list) and len(cached) > 0:
                    print("   (calendar from cache)")
                    return cached
        except Exception:
            pass  # corrupt cache, fetch fresh

    # --- Fetch from API ---
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; UK100-ORB-Filter/2.0)",
        "Accept": "application/json",
    }

    for attempt in range(4):
        try:
            resp = requests.get(FF_CALENDAR_URL, timeout=15, headers=headers)
            resp.raise_for_status()
            events = resp.json()
            # Save to cache
            try:
                with open(CALENDAR_CACHE_FILE, "w", encoding="utf-8") as f:
                    json.dump(events, f, ensure_ascii=False)
            except Exception:
                pass
            return events
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 429 and attempt < 3:
                wait = 2 ** (attempt + 1) + random.uniform(0, 1)
                print(f"   Calendar rate-limited, aguardando {wait:.0f}s...")
                _time.sleep(wait)
                continue
            print(f"    Calendar fetch failed: {e}")
            break
        except Exception as e:
            print(f"    Calendar fetch failed: {e}")
            break

    # --- Fallback: return stale cache if available ---
    if CALENDAR_CACHE_FILE.exists():
        try:
            with open(CALENDAR_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, list) and len(cached) > 0:
                print("   (using stale cache as fallback)")
                return cached
        except Exception:
            pass

    return []


def filter_events_for_today(events: list[dict], ref_date: datetime) -> dict:
    """
    Filter calendar events:
    - Only today's date (ref_date)
    - Only relevant countries (GBP, USD, EUR)
    - Classify by impact level
    - Flag if any high-impact event is near the London open window
    """
    today_str = ref_date.strftime("%Y-%m-%d")
    high_events = []
    medium_events = []
    near_open_high = []

    # London open is 08:00 UK time.  Events use US Eastern time in the JSON.
    # We'll parse the date string and check if it falls on today.
    for ev in events:
        country = ev.get("country", "")
        impact = ev.get("impact", "").strip()
        title = ev.get("title", "")
        date_str = ev.get("date", "")

        # Only relevant countries
        if country not in RELEVANT_COUNTRIES:
            continue

        # Parse date — format: "2026-04-01T08:15:00-04:00"
        try:
            ev_dt = datetime.fromisoformat(date_str)
            # Convert to UTC for consistent comparison
            ev_utc = ev_dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue

        # Check if it's today (comparing in UTC date)
        if ev_utc.date() != ref_date.date():
            # Also check if the event is in the overnight-to-morning window
            # (some events at e.g. 02:00 ET on Apr 1 = 06:00 UTC Apr 1 = today)
            yesterday = ref_date.date() - timedelta(days=1)
            if ev_utc.date() != yesterday and ev_utc.date() != ref_date.date():
                continue

        event_info = {
            "title": title,
            "country": country,
            "impact": impact,
            "time_utc": ev_utc.strftime("%H:%M UTC"),
            "forecast": ev.get("forecast", ""),
            "previous": ev.get("previous", ""),
        }

        if impact == "High":
            high_events.append(event_info)
            # Check if near London open (06:00–10:00 UTC ≈ UK time in BST/GMT)
            ev_hour_utc = ev_utc.hour
            # London open = 08:00 UK.  In GMT that's 08:00, in BST it's 07:00 UTC.
            # We use a wide window: 05:00–11:00 UTC to cover both GMT and BST.
            if 5 <= ev_hour_utc <= 11:
                near_open_high.append(event_info)
        elif impact == "Medium":
            medium_events.append(event_info)

    return {
        "high_impact_events": high_events,
        "medium_impact_events": medium_events,
        "near_open_high_impact": near_open_high,
        "has_high_impact": len(high_events) > 0,
        "has_near_open_high": len(near_open_high) > 0,
        "total_high": len(high_events),
        "total_medium": len(medium_events),
    }


def fetch_market_data() -> dict[str, dict]:
    """
    Fetch price data for all tickers via yfinance.
    Returns dict with ticker name -> {last_close, pct_change, prices_df}.
    """
    results = {}
    for name, ticker_symbol in TICKERS.items():
        try:
            ticker = yf.Ticker(ticker_symbol)
            df = ticker.history(period="5d", interval="1d")
            if df.empty or len(df) < 2:
                results[name] = {"last_close": None, "pct_change": None, "df": None}
                continue

            last_close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            pct = ((last_close - prev_close) / prev_close) * 100

            results[name] = {
                "last_close": round(last_close, 4),
                "pct_change": round(pct, 2),
                "df": df,
            }
        except Exception as e:
            print(f"    {name} ({ticker_symbol}) fetch failed: {e}")
            results[name] = {"last_close": None, "pct_change": None, "df": None}

    return results


def compute_ftse_volatility(market_data: dict) -> dict:
    """
    Compute ATR-based volatility regime + Bollinger Squeeze for FTSE.
    Returns: vol_regime, current_atr, avg_atr, atr_ratio, bb_squeeze,
             bb_width, vix_level.
    """
    ftse_data = market_data.get("FTSE", {})
    df = ftse_data.get("df")

    base = {
        "vol_regime": "unknown",
        "current_atr": None,
        "avg_atr": None,
        "atr_ratio": None,
        "bb_squeeze": None,
        "bb_width": None,
    }

    if df is None or len(df) < 5:
        return base

    # Manual ATR calculation (avoids pandas_ta import issues)
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # Simple moving average of TR as ATR proxy (we have limited data)
    atr_values = true_range.dropna()
    if len(atr_values) < 2:
        return base

    current_atr = float(atr_values.iloc[-1])
    avg_atr = float(atr_values.mean())
    atr_ratio = current_atr / avg_atr if avg_atr > 0 else 1.0

    # If current ATR > 80% of average → expansion regime
    # If current ATR < 60% of average → compression (fakeout prone)
    if atr_ratio >= 0.9:
        regime = "expansion"
    elif atr_ratio <= 0.65:
        regime = "compression"
    else:
        regime = "neutral"

    result = {
        "vol_regime": regime,
        "current_atr": round(current_atr, 2),
        "avg_atr": round(avg_atr, 2),
        "atr_ratio": round(atr_ratio, 3),
        "bb_squeeze": None,
        "bb_width": None,
    }

    # --- Bollinger Squeeze detection ---
    # BB squeeze = Bollinger Bands inside Keltner Channels → pending breakout
    try:
        sma = close.rolling(window=min(20, len(close))).mean()
        std = close.rolling(window=min(20, len(close))).std()
        bb_upper = sma + 2 * std
        bb_lower = sma - 2 * std

        # Keltner Channels (1.5x ATR)
        atr_series = true_range.rolling(window=min(20, len(true_range))).mean()
        kc_upper = sma + 1.5 * atr_series
        kc_lower = sma - 1.5 * atr_series

        # Squeeze: BB inside KC
        last_idx = -1
        if (not pd.isna(bb_upper.iloc[last_idx]) and
                not pd.isna(kc_upper.iloc[last_idx])):
            squeeze = (bb_upper.iloc[last_idx] < kc_upper.iloc[last_idx] and
                       bb_lower.iloc[last_idx] > kc_lower.iloc[last_idx])
            result["bb_squeeze"] = bool(squeeze)

            # BB width (normalized) — lower = more compressed
            mid = sma.iloc[last_idx]
            if mid > 0:
                result["bb_width"] = round(
                    (bb_upper.iloc[last_idx] - bb_lower.iloc[last_idx]) / mid * 100, 3
                )
    except Exception:
        pass  # non-critical, don't break the tool

    return result


def compute_preopen_structure(market_data: dict) -> dict:
    """
    Assess pre-open structure:
    - Is the market already extended (big overnight move)?
    - Or well-positioned for a clean breakout?
    """
    spx_pct = _safe_pct(market_data, "SPX_futures")
    dax_pct = _safe_pct(market_data, "DAX")
    ftse_pct = _safe_pct(market_data, "FTSE")
    gbp_pct = _safe_pct(market_data, "GBPUSD")

    # Extended if any major mover did > 0.8% overnight or FTSE gap > 0.6%
    big_moves = []
    for name, pct in [("SPX", spx_pct), ("DAX", dax_pct), ("FTSE", ftse_pct), ("GBPUSD", gbp_pct)]:
        if pct is not None and abs(pct) > 0.8:
            big_moves.append(f"{name}: {pct:+.2f}%")

    is_extended = len(big_moves) >= 2 or (ftse_pct is not None and abs(ftse_pct) > 1.0)

    return {
        "is_extended": is_extended,
        "big_moves": big_moves,
        "ftse_gap_pct": ftse_pct,
    }


# ---------------------------------------------------------------------------
# 5 SCORING MODULES
# Module 1 uses 0-3 scale (macro events are the #1 fakeout predictor for ORB)
# Modules 2-5 use 0-2 scale
# Total: 0-11
# ---------------------------------------------------------------------------

def score_1_macro_events(calendar_data: dict) -> tuple[int, str]:
    """
    1. EVENTOS E RISCO MACRO (0-3 pontos) — weighted heavier
       0 = Alto risco / notícias de alto impacto PERTO da abertura → EVITAR
       1 = Notícias de alto impacto hoje, perto da abertura, mas apenas 1 evento
       2 = Risco moderado (alto impacto fora da janela, ou calendário indisponível)
       3 = Dia limpo / sem eventos relevantes
    """
    if calendar_data.get("calendar_unavailable"):
        return 2, "Calendário indisponível — classificado como risco moderado por precaução."

    if calendar_data["has_near_open_high"]:
        n_near = len(calendar_data["near_open_high_impact"])
        events_str = ", ".join(
            f"{e['title']} ({e['country']} {e['time_utc']})"
            for e in calendar_data["near_open_high_impact"]
        )
        if n_near >= 2:
            return 0, f"PERIGO — {n_near} notícias de alto impacto PERTO da abertura: {events_str}"
        return 1, f"Notícia de alto impacto perto da abertura: {events_str}"

    if calendar_data["has_high_impact"]:
        return 2, (
            f"Risco moderado — {calendar_data['total_high']} evento(s) de alto impacto hoje, "
            "mas fora da janela de abertura."
        )

    if calendar_data["total_medium"] > 3:
        return 2, f"Sem alto impacto, mas {calendar_data['total_medium']} eventos de médio impacto."

    return 3, "Dia limpo. Sem eventos de alto impacto relevantes."


def score_2_global_sentiment(market_data: dict) -> tuple[int, str]:
    """
    2. SENTIMENTO GLOBAL (0–2 pontos)
       Analise: S&P 500 (futuros), DAX, Euro Stoxx 50
       0 = Indefinido / lateral / divergente
       1 = Leve viés
       2 = Forte risk-on ou risk-off (alinhado)
    """
    spx = _safe_pct(market_data, "SPX_futures")
    dax = _safe_pct(market_data, "DAX")
    stoxx = _safe_pct(market_data, "STOXX50")

    if spx is None or dax is None:
        return 0, "Dados insuficientes para avaliar sentimento global."

    # If stoxx is unavailable, use just SPX + DAX
    vals = [v for v in [spx, dax, stoxx] if v is not None]

    all_positive = all(v > 0.2 for v in vals)
    all_negative = all(v < -0.2 for v in vals)
    strong_positive = all(v > 0.5 for v in vals)
    strong_negative = all(v < -0.5 for v in vals)

    detail = f"SPX: {spx:+.2f}%, DAX: {dax:+.2f}%"
    if stoxx is not None:
        detail += f", STOXX50: {stoxx:+.2f}%"

    if strong_positive:
        return 2, f"Forte risk-on global. {detail}"
    if strong_negative:
        return 2, f"Forte risk-off global. {detail}"
    if all_positive:
        return 1, f"Leve viés positivo. {detail}"
    if all_negative:
        return 1, f"Leve viés negativo. {detail}"

    return 0, f"Sentimento indefinido/divergente. {detail}"


def score_3_correlations(market_data: dict) -> tuple[int, str]:
    """
    3. CORRELAÇÕES CHAVE (0–2 pontos)
       Avalie direção e coerência: Crude Oil, GBP/USD, Gold
       0 = Confuso / divergente
       1 = Parcialmente alinhado
       2 = Alinhamento claro com direção do índice
    """
    oil = _safe_pct(market_data, "OIL")
    gold = _safe_pct(market_data, "GOLD")
    gbp = _safe_pct(market_data, "GBPUSD")
    ftse = _safe_pct(market_data, "FTSE")

    details = []
    if oil is not None:
        details.append(f"Oil: {oil:+.2f}%")
    if gold is not None:
        details.append(f"Gold: {gold:+.2f}%")
    if gbp is not None:
        details.append(f"GBP/USD: {gbp:+.2f}%")
    detail_str = ", ".join(details) if details else "Dados indisponíveis"

    available = [v for v in [oil, gbp, gold] if v is not None]
    if len(available) < 2:
        return 0, f"Dados insuficientes. {detail_str}"

    # For a bullish FTSE day, we typically expect:
    #   GBP/USD positive (risk-on), Oil positive (growth), Gold flat/down (risk-on)
    # For bearish: opposite
    # Check coherence: are they mostly pointing the same direction?
    positive_count = sum(1 for v in available if v > 0.1)
    negative_count = sum(1 for v in available if v < -0.1)

    # Check if correlations align with FTSE direction
    ftse_direction = None
    if ftse is not None:
        ftse_direction = "bull" if ftse > 0.1 else ("bear" if ftse < -0.1 else "flat")

    if positive_count == len(available) or negative_count == len(available):
        alignment = "Alinhamento claro"
        # Extra check: does it match FTSE?
        if ftse_direction == "bull" and positive_count == len(available):
            return 2, f"{alignment} com direção do índice (bullish). {detail_str}"
        if ftse_direction == "bear" and negative_count == len(available):
            return 2, f"{alignment} com direção do índice (bearish). {detail_str}"
        return 2, f"{alignment} entre correlações. {detail_str}"

    if positive_count >= len(available) - 1 or negative_count >= len(available) - 1:
        return 1, f"Parcialmente alinhado. {detail_str}"

    return 0, f"Confuso / divergente. {detail_str}"


def score_4_volatility(vol_data: dict, market_data: dict | None = None) -> tuple[int, str]:
    """
    4. CONDIÇÃO DE VOLATILIDADE (0-2 pontos)
       Combines ATR regime + Bollinger Squeeze + VIX level.
       0 = Baixa qualidade (fakeouts prováveis / VIX extremo)
       1 = Médio
       2 = Alta probabilidade de expansão / sweet spot
    """
    regime = vol_data.get("vol_regime", "unknown")
    atr_ratio = vol_data.get("atr_ratio")
    current_atr = vol_data.get("current_atr")
    avg_atr = vol_data.get("avg_atr")
    bb_squeeze = vol_data.get("bb_squeeze")

    # VIX context
    vix_level = None
    vix_str = ""
    if market_data:
        vix_data = market_data.get("VIX", {})
        vix_level = vix_data.get("last_close")
    if vix_level is not None:
        vix_str = f", VIX: {vix_level:.1f}"

    if regime == "unknown":
        return 1, f"Dados insuficientes para avaliar volatilidade. Classificado como médio.{vix_str}"

    detail = f"ATR atual: {current_atr}, ATR médio: {avg_atr}, Ratio: {atr_ratio}{vix_str}"

    # Bollinger squeeze bonus info
    squeeze_str = ""
    if bb_squeeze is True:
        squeeze_str = " Bollinger Squeeze ATIVO — breakout iminente."
    elif bb_squeeze is False:
        squeeze_str = ""

    # VIX extreme check: VIX > 30 means chaos, even expansion is risky
    if vix_level is not None and vix_level > 30:
        return 0, f"VIX extremo ({vix_level:.1f}) — volatilidade excessiva, alto risco de fakeout. {detail}"

    if regime == "expansion":
        # VIX sweet spot (15-25) + expansion = best conditions
        if vix_level is not None and 15 <= vix_level <= 25:
            return 2, f"Condições ideais: expansão ATR + VIX em zona ótima ({vix_level:.1f}). {detail}{squeeze_str}"
        return 2, f"Alta probabilidade de expansão. Ambiente favorece breakout. {detail}{squeeze_str}"

    if regime == "compression":
        # But if BB squeeze is active, compression = pending breakout (positive)
        if bb_squeeze is True:
            return 1, f"Compressão com Bollinger Squeeze — breakout pendente. {detail}{squeeze_str}"
        return 0, f"Compressão detectada. Propenso a fakeouts. {detail}"

    # Neutral regime
    if bb_squeeze is True:
        return 2, f"Squeeze activo em regime neutro — breakout provável. {detail}{squeeze_str}"
    return 1, f"Volatilidade média/neutra. {detail}"


def score_5_preopen_structure(structure_data: dict) -> tuple[int, str]:
    """
    5. ESTRUTURA PRÉ-ABERTURA (0–2 pontos)
       0 = Esticado / exausto
       1 = Neutro
       2 = Bem posicionado para rompimento limpo
    """
    is_extended = structure_data.get("is_extended", False)
    big_moves = structure_data.get("big_moves", [])
    ftse_gap = structure_data.get("ftse_gap_pct")

    if is_extended:
        moves_str = ", ".join(big_moves) if big_moves else "múltiplos ativos estendidos"
        return 0, f"Mercado já esticado antes da abertura. {moves_str}"

    if ftse_gap is not None and abs(ftse_gap) > 0.5:
        return 1, f"FTSE gap moderado ({ftse_gap:+.2f}%). Estrutura neutra."

    if ftse_gap is not None:
        return 2, f"Bem posicionado para rompimento limpo. FTSE gap: {ftse_gap:+.2f}%"

    return 1, "Estrutura neutra. Dados de gap indisponíveis."


# ---------------------------------------------------------------------------
# DIRECTION LOGIC
# ---------------------------------------------------------------------------

def determine_direction(
    total_score: int,
    market_data: dict,
    calendar_data: dict,
) -> str:
    """
    Determine trade direction based on score + global sentiment alignment.
    Scale: 0-11 (Module 1 = 0-3, Modules 2-5 = 0-2 each).
    Returns: "COMPRADO" / "VENDIDO" / "NÃO OPERAR"
    """
    if total_score < 5:
        return "NÃO OPERAR"

    spx = _safe_pct(market_data, "SPX_futures")
    dax = _safe_pct(market_data, "DAX")
    ftse = _safe_pct(market_data, "FTSE")
    gbp = _safe_pct(market_data, "GBPUSD")

    # Build a directional consensus
    bullish_signals = 0
    bearish_signals = 0

    for val in [spx, dax, ftse, gbp]:
        if val is not None:
            if val > 0.15:
                bullish_signals += 1
            elif val < -0.15:
                bearish_signals += 1

    if total_score >= 8:
        # Strong day — go with consensus
        if bullish_signals >= 3:
            return "COMPRADO"
        if bearish_signals >= 3:
            return "VENDIDO"
        if bullish_signals > bearish_signals:
            return "COMPRADO"
        if bearish_signals > bullish_signals:
            return "VENDIDO"
        return "NÃO OPERAR"

    if total_score >= 5:
        # Cautious day — need strong consensus
        if bullish_signals >= 3:
            return "COMPRADO"
        if bearish_signals >= 3:
            return "VENDIDO"
        return "NÃO OPERAR"

    return "NÃO OPERAR"


# ---------------------------------------------------------------------------
# OUTPUT FORMATTING
# ---------------------------------------------------------------------------

def format_classification(score: int) -> str:
    """Classify score on 0-11 scale."""
    if score >= 8:
        return "DIA FAVORÁVEL"
    if score >= 5:
        return "OPERAR COM CAUTELA"
    return "NÃO OPERAR"


def format_direction(direction: str) -> str:
    if direction == "COMPRADO":
        return "COMPRADO (Long)"
    if direction == "VENDIDO":
        return "VENDIDO (Short)"
    return "NÃO OPERAR"


def build_summary(
    scores: list[tuple[int, str]],
    total_score: int,
    direction: str,
    calendar_data: dict,
    market_data: dict,
) -> str:
    """Build concise 5-line summary (max) for the final output."""
    lines = []

    # Line 1: Overall assessment
    if total_score >= 8:
        lines.append("Dia com condições favoráveis para ORB com continuidade.")
    elif total_score >= 5:
        lines.append("Condições mistas. Risco de fakeout moderado. Reduzir exposição.")
    else:
        lines.append("Condições desfavoráveis. Alto risco de fakeout. Recomendação: não operar.")

    # Line 2: Key macro context
    macro_score, macro_detail = scores[0]
    if macro_score <= 1:
        lines.append(f"Macro: {macro_detail}")
    elif macro_score == 3:
        lines.append("Calendário limpo — sem notícias de alto impacto perto da abertura.")

    # Line 3: Sentiment + direction
    spx = _safe_pct(market_data, "SPX_futures")
    dax = _safe_pct(market_data, "DAX")
    if spx is not None and dax is not None:
        lines.append(f"Futuros: SPX {spx:+.2f}%, DAX {dax:+.2f}%. Direção: {direction}.")

    # Line 4: Volatility context
    vol_score, vol_detail = scores[3]
    if vol_score == 0:
        lines.append("Volatilidade comprimida — cuidado com fakeouts.")
    elif vol_score == 2:
        lines.append("Volatilidade em expansão — bom para breakouts.")

    # Line 5: Pre-open
    struct_score, struct_detail = scores[4]
    if struct_score == 0:
        lines.append("Estrutura pré-abertura esticada. Aguardar.")

    return "\n".join(lines[:5])


def print_full_output(
    scores: list[tuple[int, str]],
    total_score: int,
    classification: str,
    direction: str,
    summary: str,
    calendar_data: dict,
    market_data: dict,
    vol_data: dict,
    structure_data: dict,
    show_raw: bool = False,
):
    """Print the complete formatted output."""
    now = datetime.now()
    section_names = [
        "1. EVENTOS E RISCO MACRO",
        "2. SENTIMENTO GLOBAL",
        "3. CORRELAÇÕES CHAVE",
        "4. CONDIÇÃO DE VOLATILIDADE",
        "5. ESTRUTURA PRÉ-ABERTURA",
    ]

    print()
    print("=" * 64)
    print("   UK100 ORB PRE-OPEN INSTITUTIONAL FILTER")
    print(f"   {now.strftime('%A, %d %B %Y')} — {now.strftime('%H:%M:%S')} (local)")
    print("=" * 64)
    print()

    # Individual module scores
    max_scores = [3, 2, 2, 2, 2]  # Module 1 = 0-3, rest = 0-2
    for i, (score_val, detail) in enumerate(scores):
        mx = max_scores[i]
        bar = "#" * score_val + "." * (mx - score_val)
        print(f"  {section_names[i]}")
        print(f"    Score: {score_val}/{mx}  [{bar}]")
        print(f"    {detail}")
        print()

    # Final output in the exact fixed format
    print("-" * 64)
    print()
    print(f"   Score: {total_score}/11")
    print(f"   Classificação: {classification}")
    print(f"   Direção: {format_direction(direction)}")
    print()
    print("   Resumo:")
    for line in summary.split("\n"):
        print(f"     {line}")
    print()
    print("-" * 64)

    # Futures snapshot
    print()
    print("   SNAPSHOT DOS MERCADOS:")
    for name in ["SPX_futures", "DAX", "STOXX50", "OIL", "GOLD", "GBPUSD", "FTSE", "VIX"]:
        data = market_data.get(name, {})
        pct = data.get("pct_change")
        last = data.get("last_close")
        if pct is not None and last is not None:
            arrow = "+" if pct > 0 else ("-" if pct < 0 else "=")
            display_names = {
                "SPX_futures": "S&P 500 fut",
                "DAX": "DAX",
                "STOXX50": "Euro Stoxx",
                "OIL": "Crude Oil",
                "GOLD": "Gold",
                "GBPUSD": "GBP/USD",
                "FTSE": "FTSE 100",
                "VIX": "VIX",
            }
            label = display_names.get(name, name)
            print(f"    {label:>12s}: {last:>10.2f}  {arrow} {pct:+.2f}%")
        else:
            print(f"    {name:>12s}: dados indisponíveis")

    # Volatility
    print()
    regime = vol_data.get("vol_regime", "?")
    atr = vol_data.get("current_atr", "?")
    avg = vol_data.get("avg_atr", "?")
    ratio = vol_data.get("atr_ratio", "?")
    print(f"   Volatilidade: {regime} (ATR: {atr}, Média: {avg}, Ratio: {ratio})")
    bb_squeeze = vol_data.get("bb_squeeze")
    if bb_squeeze is True:
        print("   Bollinger Squeeze ATIVO — breakout iminente.")

    # Calendar highlights
    if calendar_data.get("near_open_high_impact"):
        print()
        print("   ALERTAS DE CALENDÁRIO (alto impacto perto da abertura):")
        for ev in calendar_data["near_open_high_impact"]:
            print(f"    • {ev['time_utc']} — {ev['title']} ({ev['country']})")

    if calendar_data.get("high_impact_events"):
        remaining = [
            e for e in calendar_data["high_impact_events"]
            if e not in calendar_data.get("near_open_high_impact", [])
        ]
        if remaining:
            print()
            print("   Outros eventos de alto impacto hoje:")
            for ev in remaining:
                print(f"    • {ev['time_utc']} — {ev['title']} ({ev['country']})")

    print()
    print("=" * 64)
    print()

    if show_raw:
        print("\n--- RAW DATA (debug) ---")
        raw = {
            "calendar": calendar_data,
            "market": {
                k: {"last_close": v["last_close"], "pct_change": v["pct_change"]}
                for k, v in market_data.items()
            },
            "volatility": {k: v for k, v in vol_data.items() if k != "df"},
            "structure": structure_data,
            "scores": [
                {"module": section_names[i], "score": s, "detail": d}
                for i, (s, d) in enumerate(scores)
            ],
            "total_score": total_score,
            "classification": classification,
            "direction": direction,
        }
        print(json.dumps(raw, indent=2, ensure_ascii=False))


def output_json(
    scores: list[tuple[int, str]],
    total_score: int,
    classification: str,
    direction: str,
    summary: str,
    calendar_data: dict,
    market_data: dict,
    vol_data: dict,
    structure_data: dict,
):
    """Output the analysis as a JSON object."""
    section_names = [
        "macro_events",
        "global_sentiment",
        "correlations",
        "volatility",
        "preopen_structure",
    ]
    result = {
        "timestamp": datetime.now().isoformat(),
        "score": total_score,
        "classification": classification,
        "direction": direction,
        "summary": summary,
        "modules": {
            section_names[i]: {"score": s, "max": 3 if i == 0 else 2, "detail": d}
            for i, (s, d) in enumerate(scores)
        },
        "market_snapshot": {
            k: {"last_close": v["last_close"], "pct_change": v["pct_change"]}
            for k, v in market_data.items()
        },
        "volatility": {
            k: v for k, v in vol_data.items()
            if k not in ("df",)
        },
        "calendar": {
            "high_impact_count": calendar_data["total_high"],
            "near_open_high": calendar_data["has_near_open_high"],
            "events": calendar_data.get("high_impact_events", []),
        },
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _safe_pct(market_data: dict, key: str) -> float | None:
    """Safely get pct_change from market data."""
    data = market_data.get(key, {})
    return data.get("pct_change") if data else None


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def run_analysis(show_raw: bool = False, output_format: str = "text",
                 use_ollama: bool = False, ollama_model: str = DEFAULT_OLLAMA_MODEL) -> dict:
    """
    Run the complete pre-open analysis pipeline.
    If use_ollama=True, feeds real data to local LLM for institutional analysis.
    Returns a dict with all results.
    """
    now = datetime.now()

    if output_format == "text":
        mode_label = f"Ollama ({ollama_model})" if use_ollama else "Rule-based"
        print(f"\n  UK100 ORB Pre-Open Filter [{mode_label}] — a correr às {now.strftime('%H:%M:%S')}")
        print("  A buscar dados reais...\n")

    # 1. Fetch data
    if output_format == "text":
        print("  [1/3] Calendário económico...")
    raw_calendar = fetch_economic_calendar()
    calendar_available = len(raw_calendar) > 0
    calendar_data = filter_events_for_today(raw_calendar, now)
    if not calendar_available:
        calendar_data["calendar_unavailable"] = True

    if output_format == "text":
        print("  [2/3] Dados de mercado (futuros, FX, índices)...")
    market_data = fetch_market_data()

    if output_format == "text":
        print("  [3/3] Volatilidade e estrutura pré-abertura...")
    vol_data = compute_ftse_volatility(market_data)
    structure_data = compute_preopen_structure(market_data)

    if output_format == "text":
        print("\n   Dados carregados. A calcular scores...\n")

    # ---------------------------------------------------------------
    # BRANCH: Ollama LLM mode vs Rule-based mode
    # ---------------------------------------------------------------
    if use_ollama:
        # === OLLAMA MODE: Feed real data to local LLM ===
        ollama_result = ollama_scoring(
            calendar_data, market_data, vol_data, structure_data,
            model=ollama_model,
        )

        if ollama_result is None:
            print("   Ollama falhou. A usar scoring rule-based como fallback...\n")
            use_ollama = False  # Fall through to rule-based below
        else:
            # Output
            if output_format == "json":
                json_result = {
                    "timestamp": now.isoformat(),
                    "mode": "ollama",
                    "model": ollama_result.get("model"),
                    "response_time_s": ollama_result.get("response_time_s"),
                    "score": ollama_result.get("score"),
                    "classification": ollama_result.get("classification"),
                    "direction": ollama_result.get("direction"),
                    "summary": ollama_result.get("summary"),
                    "market_snapshot": {
                        k: {"last_close": v.get("last_close"), "pct_change": v.get("pct_change")}
                        for k, v in market_data.items()
                    },
                    "volatility": {k: v for k, v in vol_data.items() if k != "df"},
                    "calendar": {
                        "high_impact_count": calendar_data.get("total_high", 0),
                        "near_open_high": calendar_data.get("has_near_open_high", False),
                        "events": calendar_data.get("high_impact_events", []),
                    },
                }
                if show_raw:
                    json_result["raw_llm_response"] = ollama_result.get("raw_llm_response")
                print(json.dumps(json_result, indent=2, ensure_ascii=False))
            else:
                print_ollama_output(
                    ollama_result, calendar_data, market_data,
                    vol_data, structure_data, show_raw=show_raw,
                )

            # Save
            result = {
                "timestamp": now.isoformat(),
                "mode": "ollama",
                "model": ollama_result.get("model"),
                "score": ollama_result.get("score"),
                "classification": ollama_result.get("classification"),
                "direction": ollama_result.get("direction"),
                "summary": ollama_result.get("summary"),
            }
            try:
                with open("last_analysis.json", "w", encoding="utf-8") as f:
                    json.dump(result, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
            return result

    # === RULE-BASED MODE (fast, deterministic) ===

    # 2. Score all 5 modules
    s1 = score_1_macro_events(calendar_data)
    s2 = score_2_global_sentiment(market_data)
    s3 = score_3_correlations(market_data)
    s4 = score_4_volatility(vol_data, market_data)
    s5 = score_5_preopen_structure(structure_data)

    scores = [s1, s2, s3, s4, s5]
    total_score = sum(s for s, _ in scores)

    # 3. Classification + direction
    classification = format_classification(total_score)
    direction = determine_direction(total_score, market_data, calendar_data)

    # 4. Summary
    summary = build_summary(scores, total_score, direction, calendar_data, market_data)

    # 5. Output
    if output_format == "json":
        output_json(
            scores, total_score, classification, direction, summary,
            calendar_data, market_data, vol_data, structure_data,
        )
    else:
        print_full_output(
            scores, total_score, classification, direction, summary,
            calendar_data, market_data, vol_data, structure_data,
            show_raw=show_raw,
        )

    # 6. Save last analysis to JSON file for potential dashboard/telegram use
    result = {
        "timestamp": now.isoformat(),
        "mode": "rule-based",
        "score": total_score,
        "classification": classification,
        "direction": direction,
        "summary": summary,
    }
    try:
        with open("last_analysis.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # non-critical

    return result


def main():
    parser = argparse.ArgumentParser(
        description="UK100 ORB Pre-Open Institutional Filter — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python uk100_orb_filter.py                    # Rule-based (instant)
  python uk100_orb_filter.py --ollama           # Ollama LLM institutional analysis
  python uk100_orb_filter.py --ollama --model mistral:7b-instruct-q4_K_M
  python uk100_orb_filter.py --ollama --raw     # Ollama + show raw LLM response
  python uk100_orb_filter.py --json             # Output as JSON only
        """,
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Print raw data at the end for debugging",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output result as JSON (machine-readable)",
    )
    parser.add_argument(
        "--ollama", action="store_true",
        help="Use local Ollama LLM for institutional-grade analysis (requires ollama running)",
    )
    parser.add_argument(
        "--model", type=str, default=DEFAULT_OLLAMA_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_OLLAMA_MODEL}). "
             f"Examples: llama3:8b, mistral:7b-instruct-q4_K_M, llama3.1:8b",
    )
    args = parser.parse_args()

    output_format = "json" if args.json else "text"
    run_analysis(
        show_raw=args.raw,
        output_format=output_format,
        use_ollama=args.ollama,
        ollama_model=args.model,
    )


if __name__ == "__main__":
    main()
