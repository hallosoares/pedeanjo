#!/usr/bin/env python3
"""
UK100 ORB Pre-Open Institutional Filter
=========================================================
Run before the London open (~07:15 UK time) to get a scored
pre-open analysis for the FTSE 100 Opening Range Breakout strategy.

Usage:
    python uk100_orb_filter.py          # full analysis (default)
    python uk100_orb_filter.py --raw    # also print raw fetched data
    python uk100_orb_filter.py --json   # output as JSON
    python uk100_orb_filter.py --help   # show help

Data sources (all free, no API keys):
    - yfinance        : Futures, FX, FTSE prices, ATR, volume, VIX
    - ForexFactory    : Economic calendar with impact levels (cached locally)

Author : fesimon (pedeanjo)
Version: 6.0.0
"""

import argparse
import json
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

from signals import (
    compute_vix_term_structure,
    compute_bond_yield_curve,
    compute_intermarket_divergence,
    compute_seasonality,
    compute_currency_strength,
)

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
    "NIKKEI":      "^N225",      # Nikkei 225 (Asian session lead)
    "HSI":         "^HSI",       # Hang Seng Index (Asian session lead)
}

# ForexFactory calendar URL (free, no key)
FF_CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

# ATR parameters
ATR_PERIOD = 14
HISTORY_DAYS = "1mo"  # enough for ATR calculation

# Calendar cache — avoids 429 rate-limit on repeated runs
CALENDAR_CACHE_FILE = Path(__file__).parent / ".calendar_cache.json"
CALENDAR_CACHE_TTL_MIN = 30  # minutes

# Session log — append-only history for accuracy tracking
ANALYSIS_LOG_FILE = Path(__file__).parent / "analysis_log.jsonl"


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

    # --- Try cache first ---
    if CALENDAR_CACHE_FILE.exists():
        try:
            cache_age_min = (_time.time() - CALENDAR_CACHE_FILE.stat().st_mtime) / 60
            if cache_age_min < CALENDAR_CACHE_TTL_MIN:
                with open(CALENDAR_CACHE_FILE, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if isinstance(cached, list) and len(cached) > 0:
                    print("   (calendar from cache)", file=__import__("sys").stderr)
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
                print(f"   Calendar rate-limited, aguardando {wait:.0f}s...", file=__import__("sys").stderr)
                _time.sleep(wait)
                continue
            print(f"    Calendar fetch failed: {e}", file=__import__("sys").stderr)
            break
        except Exception as e:
            print(f"    Calendar fetch failed: {e}", file=__import__("sys").stderr)
            break

    # --- Fallback: return stale cache if available ---
    if CALENDAR_CACHE_FILE.exists():
        try:
            with open(CALENDAR_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if isinstance(cached, list) and len(cached) > 0:
                print("   (using stale cache as fallback)", file=__import__("sys").stderr)
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
            # FTSE needs 1mo for ATR, RSI and multi-day trend; others need only 5d
            hist_period = "1mo" if name in ("FTSE", "VIX") else "5d"
            df = ticker.history(period=hist_period, interval="1d")
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
            print(f"    {name} ({ticker_symbol}) fetch failed: {e}", file=__import__("sys").stderr)
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


def compute_ftse_rsi(market_data: dict, period: int = 14) -> dict:
    """
    Compute RSI for FTSE 100 using daily closes (last 1 month of data).
    Uses Wilder's smoothed RSI method.

    Returns:
        rsi           : float | None
        zone          : "overbought" (>70) | "oversold" (<30) | "neutral"
        signal        : "caution_long" | "caution_short" | "neutral"
        detail        : human-readable string
    """
    ftse_data = market_data.get("FTSE", {})
    df = ftse_data.get("df")

    base = {
        "rsi": None,
        "zone": "unknown",
        "signal": "neutral",
        "detail": "RSI FTSE indisponível.",
    }

    if df is None or len(df) < period + 1:
        return base

    closes = df["Close"].dropna()
    if len(closes) < period + 1:
        return base

    deltas = closes.diff().dropna()
    gains = deltas.clip(lower=0)
    losses = (-deltas).clip(lower=0)

    # Wilder smoothing (EWM with alpha = 1/period)
    avg_gain = gains.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().iloc[-1]
    avg_loss = losses.ewm(alpha=1 / period, min_periods=period, adjust=False).mean().iloc[-1]

    if avg_loss == 0:
        rsi = 100.0
    else:
        rs = avg_gain / avg_loss
        rsi = round(100 - (100 / (1 + rs)), 1)

    if rsi >= 70:
        zone = "overbought"
        signal = "caution_long"
        detail = f"RSI {rsi} — FTSE sobrecomprado. Breakout long com menor convicção. Favorecer shorts."
    elif rsi <= 30:
        zone = "oversold"
        signal = "caution_short"
        detail = f"RSI {rsi} — FTSE sobrevendido. Potencial de bounce. Favorecer longs."
    elif rsi >= 60:
        zone = "neutral"
        signal = "neutral"
        detail = f"RSI {rsi} — zona neutra-alta. Momentum positivo."
    elif rsi <= 40:
        zone = "neutral"
        signal = "neutral"
        detail = f"RSI {rsi} — zona neutra-baixa. Momentum negativo."
    else:
        zone = "neutral"
        signal = "neutral"
        detail = f"RSI {rsi} — zona neutra. Sem extremos."

    return {"rsi": rsi, "zone": zone, "signal": signal, "detail": detail}


def compute_asian_session(market_data: dict) -> dict:
    """
    Analyse the Asian session overnight performance (Nikkei + Hang Seng).
    These are the primary drivers of the gap the FTSE opens with.

    Returns:
        direction  : "risk_on" | "risk_off" | "mixed" | "flat"
        nikkei_pct : Nikkei % change (last close)
        hsi_pct    : Hang Seng % change (last close)
        strength   : "strong" | "moderate" | "weak"
        score_hint : +1 (risk-on tailwind for FTSE), 0 (mixed/flat), -1 (risk-off headwind)
        detail     : human-readable string
    """
    nikkei_pct = _safe_pct(market_data, "NIKKEI")
    hsi_pct = _safe_pct(market_data, "HSI")

    base = {
        "direction": "unknown",
        "nikkei_pct": nikkei_pct,
        "hsi_pct": hsi_pct,
        "strength": "unknown",
        "score_hint": 0,
        "detail": "Dados asiáticos indisponíveis.",
    }

    available = [(v, name) for v, name in [(nikkei_pct, "Nikkei"), (hsi_pct, "HSI")] if v is not None]
    if not available:
        return base

    vals = [v for v, _ in available]
    parts = [f"{name}: {v:+.2f}%" for v, name in available]
    detail_base = " | ".join(parts)

    positive = sum(1 for v in vals if v > 0.2)
    negative = sum(1 for v in vals if v < -0.2)
    strong_positive = sum(1 for v in vals if v > 0.8)
    strong_negative = sum(1 for v in vals if v < -0.8)

    if positive == len(vals):
        direction = "risk_on"
        strength = "strong" if strong_positive == len(vals) else "moderate"
        hint = 1
        detail = f"Sessão asiática risk-on — {detail_base}. Tailwind para FTSE."
    elif negative == len(vals):
        direction = "risk_off"
        strength = "strong" if strong_negative == len(vals) else "moderate"
        hint = -1
        detail = f"Sessão asiática risk-off — {detail_base}. Headwind para FTSE."
    elif len(vals) == 1:
        v = vals[0]
        if v > 0.5:
            direction, strength, hint = "risk_on", "moderate", 1
            detail = f"Sessão asiática levemente positiva — {detail_base}."
        elif v < -0.5:
            direction, strength, hint = "risk_off", "moderate", -1
            detail = f"Sessão asiática levemente negativa — {detail_base}."
        else:
            direction, strength, hint = "flat", "weak", 0
            detail = f"Sessão asiática plana — {detail_base}."
    else:
        direction = "mixed"
        strength = "weak"
        hint = 0
        detail = f"Sessão asiática mista — {detail_base}. Sem viés claro."

    return {
        "direction": direction,
        "nikkei_pct": nikkei_pct,
        "hsi_pct": hsi_pct,
        "strength": strength,
        "score_hint": hint,
        "detail": detail,
    }


def compute_ftse_volume_profile(market_data: dict) -> dict:
    """
    Analyse FTSE 100 volume over the last 5 days.
    Detects volume spikes (institutional activity) vs dry volume (no conviction).

    Returns:
        volume_spike_ratio : recent vol / 5-day average (>1.5 = spike, <0.7 = dry)
        volume_trend       : "spike" | "high" | "normal" | "dry"
        volume_score_hint  : +1 (spike = conviction), 0 (normal), -1 (dry = no follow-through)
        detail             : human-readable string
    """
    ftse_data = market_data.get("FTSE", {})
    df = ftse_data.get("df")

    base = {
        "volume_spike_ratio": None,
        "volume_trend": "unknown",
        "volume_score_hint": 0,
        "detail": "Volume FTSE indisponível.",
    }

    if df is None or "Volume" not in df.columns or len(df) < 3:
        return base

    volumes = df["Volume"].dropna().tolist()
    if len(volumes) < 2:
        return base

    # Most recent session volume vs average of prior sessions
    recent_vol = volumes[-1]
    prior_vols = volumes[:-1]
    avg_vol = sum(prior_vols) / len(prior_vols) if prior_vols else recent_vol

    if avg_vol == 0:
        return base

    ratio = recent_vol / avg_vol

    if ratio >= 1.5:
        trend = "spike"
        hint = 1
        detail = f"Volume spike ({ratio:.2f}x média) — presença institucional, breakout com convicção."
    elif ratio >= 1.1:
        trend = "high"
        hint = 1
        detail = f"Volume acima da média ({ratio:.2f}x) — boa participação."
    elif ratio >= 0.75:
        trend = "normal"
        hint = 0
        detail = f"Volume normal ({ratio:.2f}x média)."
    else:
        trend = "dry"
        hint = -1
        detail = f"Volume seco ({ratio:.2f}x média) — baixa convicção, risco de fakeout aumentado."

    return {
        "volume_spike_ratio": round(ratio, 2),
        "volume_trend": trend,
        "volume_score_hint": hint,
        "detail": detail,
    }


def compute_multiday_trend(market_data: dict) -> dict:
    """
    Analyse FTSE 100 multi-day price trend (last 5-10 days).
    Answers: is the market in a sustained trend or choppy/ranging?

    Returns:
        direction       : "up" | "down" | "flat"
        consistency     : fraction of days agreeing with direction (0.0-1.0)
        momentum        : recent momentum vs earlier momentum ("accelerating"|"fading"|"stable")
        days_analysed   : int
        detail          : human-readable string
        trend_score_hint: +1 (clear trend), 0 (mixed), -1 (choppy/ranging)
    """
    ftse_data = market_data.get("FTSE", {})
    df = ftse_data.get("df")

    base = {
        "direction": "unknown",
        "consistency": 0.0,
        "momentum": "unknown",
        "days_analysed": 0,
        "detail": "Dados insuficientes para análise multi-day.",
        "trend_score_hint": 0,
    }

    if df is None or len(df) < 3:
        return base

    closes = df["Close"].dropna().tolist()
    if len(closes) < 3:
        return base

    # Daily returns
    returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]
    n = len(returns)

    up_days = sum(1 for r in returns if r > 0.001)
    down_days = sum(1 for r in returns if r < -0.001)

    if up_days > down_days:
        direction = "up"
        consistency = up_days / n
    elif down_days > up_days:
        direction = "down"
        consistency = down_days / n
    else:
        direction = "flat"
        consistency = 0.5

    # Momentum: compare recent half vs earlier half
    mid = n // 2
    earlier = sum(returns[:mid]) / mid if mid > 0 else 0
    recent = sum(returns[mid:]) / (n - mid) if (n - mid) > 0 else 0

    if direction == "up":
        momentum = "accelerating" if recent > earlier else ("fading" if recent < earlier * 0.5 else "stable")
    elif direction == "down":
        momentum = "accelerating" if recent < earlier else ("fading" if recent > earlier * 0.5 else "stable")
    else:
        momentum = "stable"

    # Score hint
    if consistency >= 0.7 and momentum != "fading":
        hint = 1
    elif consistency <= 0.45 or direction == "flat":
        hint = -1
    else:
        hint = 0

    pct_total = (closes[-1] - closes[0]) / closes[0] * 100
    detail = (
        f"Tendência {direction} ({n} dias): {up_days}d sobe / {down_days}d desce. "
        f"Consistência: {consistency:.0%}. Momentum: {momentum}. "
        f"Variação total: {pct_total:+.2f}%."
    )

    return {
        "direction": direction,
        "consistency": round(consistency, 2),
        "momentum": momentum,
        "days_analysed": n,
        "detail": detail,
        "trend_score_hint": hint,
    }


# ---------------------------------------------------------------------------
# 6 SCORING MODULES
# Module 1 uses 0-3 scale (macro events are the #1 fakeout predictor for ORB)
# Modules 2-5 use 0-2 scale
# Module 6 uses 0-3 scale (advanced signals aggregate)
# Total: 0-14
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


def score_2_global_sentiment(
    market_data: dict,
    asian_data: dict | None = None,
) -> tuple[int, str]:
    """
    2. SENTIMENTO GLOBAL (0–2 pontos)
       Analise: S&P 500 (futuros), DAX, Euro Stoxx 50 + sessão asiática.
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

    # Asian session confirmation / tiebreaker
    asian_hint = 0
    asian_str = ""
    if asian_data and asian_data.get("direction") not in ("unknown", None):
        asian_hint = asian_data.get("score_hint", 0)
        asian_str = f" | Ásia: {asian_data.get('detail', '')}"

    if strong_positive:
        return 2, f"Forte risk-on global. {detail}{asian_str}"
    if strong_negative:
        return 2, f"Forte risk-off global. {detail}{asian_str}"
    if all_positive:
        return 1, f"Leve viés positivo. {detail}{asian_str}"
    if all_negative:
        return 1, f"Leve viés negativo. {detail}{asian_str}"

    # Divergent Western markets — Asian session breaks the tie
    if asian_hint == 1:
        return 1, f"Sentimento ocidental divergente, mas Ásia risk-on. {detail}{asian_str}"
    if asian_hint == -1:
        return 1, f"Sentimento ocidental divergente, com Ásia risk-off. {detail}{asian_str}"

    return 0, f"Sentimento indefinido/divergente. {detail}{asian_str}"


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


def score_4_volatility(
    vol_data: dict,
    market_data: dict | None = None,
    volume_data: dict | None = None,
    rsi_data: dict | None = None,
) -> tuple[int, str]:
    """
    4. CONDIÇÃO DE VOLATILIDADE (0-2 pontos)
       Combines ATR regime + Bollinger Squeeze + VIX + FTSE volume + FTSE RSI.
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

    # Volume context
    vol_hint = 0
    vol_hint_str = ""
    if volume_data:
        vol_hint = volume_data.get("volume_score_hint", 0)
        vol_detail = volume_data.get("detail", "")
        vol_hint_str = f" | {vol_detail}"

    # RSI context — overbought/oversold reduces conviction for breakout continuation
    rsi_penalty = 0
    rsi_str = ""
    if rsi_data and rsi_data.get("rsi") is not None:
        rsi_zone = rsi_data.get("zone", "neutral")
        rsi_val = rsi_data.get("rsi")
        if rsi_zone == "overbought":
            rsi_penalty = -1
            rsi_str = f" | RSI {rsi_val} — sobrecomprado, cuidado."
        elif rsi_zone == "oversold":
            rsi_penalty = -1
            rsi_str = f" | RSI {rsi_val} — sobrevendido, potencial de bounce."
        else:
            rsi_str = f" | RSI {rsi_val}"

    if regime == "unknown":
        return 1, f"Dados insuficientes para avaliar volatilidade.{vix_str}"

    detail = f"ATR atual: {current_atr}, ATR médio: {avg_atr}, Ratio: {atr_ratio}{vix_str}"

    squeeze_str = " Bollinger Squeeze ATIVO — breakout iminente." if bb_squeeze is True else ""

    # VIX extreme check: VIX > 30 = chaos
    if vix_level is not None and vix_level > 30:
        return 0, f"VIX extremo ({vix_level:.1f}) — volatilidade excessiva, risco de fakeout. {detail}"

    if regime == "expansion":
        base_score = 2
        if vix_level is not None and 15 <= vix_level <= 25:
            msg = f"Condições ideais: expansão ATR + VIX zona ótima ({vix_level:.1f}). {detail}{squeeze_str}{vol_hint_str}{rsi_str}"
        else:
            msg = f"Expansão ATR. Ambiente favorece breakout. {detail}{squeeze_str}{vol_hint_str}{rsi_str}"
        # Volume dry or RSI extreme on expansion = caution
        return max(1, base_score + min(0, vol_hint) + min(0, rsi_penalty)), msg

    if regime == "compression":
        if bb_squeeze is True:
            return 1, f"Compressão com Bollinger Squeeze — breakout pendente. {detail}{squeeze_str}{vol_hint_str}{rsi_str}"
        # Dry volume + compression = worst case
        score = max(0, -1 + (1 if vol_hint >= 0 else 0) + (0 if rsi_penalty else 0))
        return score, f"Compressão detectada. Propenso a fakeouts. {detail}{vol_hint_str}{rsi_str}"

    # Neutral regime — volume + RSI hints shift it
    if bb_squeeze is True:
        return 2, f"Squeeze em regime neutro — breakout provável. {detail}{squeeze_str}{vol_hint_str}{rsi_str}"
    base = 1 + vol_hint + min(0, rsi_penalty)
    return max(0, min(2, base)), f"Volatilidade neutra. {detail}{vol_hint_str}{rsi_str}"


def score_5_preopen_structure(
    structure_data: dict,
    trend_data: dict | None = None,
) -> tuple[int, str]:
    """
    5. ESTRUTURA PRÉ-ABERTURA (0-2 pontos)
       Combines overnight extension check + multi-day trend context.
       0 = Esticado / exausto / tendência inconsistente
       1 = Neutro
       2 = Bem posicionado para rompimento limpo
    """
    is_extended = structure_data.get("is_extended", False)
    big_moves = structure_data.get("big_moves", [])
    ftse_gap = structure_data.get("ftse_gap_pct")

    # Multi-day trend context
    trend_hint = 0
    trend_str = ""
    if trend_data and trend_data.get("direction") != "unknown":
        trend_hint = trend_data.get("trend_score_hint", 0)
        direction = trend_data.get("direction", "?")
        consistency = trend_data.get("consistency", 0)
        momentum = trend_data.get("momentum", "?")
        trend_str = f" | Tendência {direction} ({consistency:.0%} consistência, momentum {momentum})."

    if is_extended:
        moves_str = ", ".join(big_moves) if big_moves else "múltiplos ativos estendidos"
        return 0, f"Mercado já esticado antes da abertura. {moves_str}{trend_str}"

    if ftse_gap is not None and abs(ftse_gap) > 0.5:
        # Moderate gap — trend can tip it
        base = 1
        score = max(0, min(2, base + trend_hint))
        return score, f"FTSE gap moderado ({ftse_gap:+.2f}%).{trend_str}"

    if ftse_gap is not None:
        # Clean gap — trend seals it
        base = 2
        score = max(0, min(2, base + min(0, trend_hint)))  # trend can only hurt here, not add
        return score, f"Estrutura limpa. FTSE gap: {ftse_gap:+.2f}%.{trend_str}"

    # No gap data — fall back to trend hint
    base = 1
    score = max(0, min(2, base + trend_hint))
    return score, f"Dados de gap indisponíveis.{trend_str}"


def score_6_advanced_signals(
    vix_ts_data: dict,
    bond_data: dict,
    divergence_data: dict,
    seasonality_data: dict,
    currency_data: dict,
) -> tuple[int, str]:
    """
    6. SINAIS AVANÇADOS (0-3 pontos)
       Combines 5 new edge signals:
       - VIX term structure (contango/backwardation)
       - Bond yield curve (normal/inverted)
       - Intermarket divergence (aligned/divergent)
       - Day-of-week seasonality (trend day / reversion day)
       - GBP currency strength (strong/weak/mixed)

       Each signal contributes a hint (+1, 0, -1).
       Sum of hints → mapped to 0-3 scale.
       0 = Majority negative signals (multiple headwinds)
       1 = Mixed / neutral
       2 = Slightly positive
       3 = Strong alignment — multiple tailwinds
    """
    hints = []
    details = []

    # VIX term structure
    vix_hint = vix_ts_data.get("score_hint", 0)
    hints.append(vix_hint)
    vix_struct = vix_ts_data.get("structure", "?")
    details.append(f"VIX: {vix_struct}")

    # Bond yield curve
    bond_hint = bond_data.get("score_hint", 0)
    hints.append(bond_hint)
    bond_regime = bond_data.get("regime", "?")
    details.append(f"Yields: {bond_regime}")

    # Intermarket divergence
    div_hint = divergence_data.get("score_hint", 0)
    hints.append(div_hint)
    div_level = divergence_data.get("divergence_level", "?")
    details.append(f"Divergência: {div_level}")

    # Seasonality
    season_hint = seasonality_data.get("score_hint", 0)
    hints.append(season_hint)
    day_name = seasonality_data.get("day_name", "?")
    quality = seasonality_data.get("quality", "?")
    details.append(f"{day_name} ({quality})")

    # Currency strength
    curr_hint = currency_data.get("score_hint", 0)
    hints.append(curr_hint)
    gbp_str = currency_data.get("gbp_strength", "?")
    details.append(f"GBP: {gbp_str}")

    # Sum hints: range is -5 to +5 → map to 0-3
    total_hint = sum(hints)
    detail_str = " | ".join(details)

    if total_hint >= 4:
        return 3, f"Forte alinhamento de sinais avançados ({total_hint:+d}). {detail_str}"
    if total_hint >= 2:
        return 2, f"Sinais avançados positivos ({total_hint:+d}). {detail_str}"
    if total_hint >= 0:
        return 1, f"Sinais avançados neutros ({total_hint:+d}). {detail_str}"
    if total_hint >= -2:
        return 0, f"Sinais avançados negativos ({total_hint:+d}). {detail_str}"
    return 0, f"Múltiplos headwinds ({total_hint:+d}). {detail_str}"


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
    Scale: 0-14 (Module 1 = 0-3, Modules 2-5 = 0-2 each, Module 6 = 0-3).
    Returns: "COMPRADO" / "VENDIDO" / "NÃO OPERAR"
    """
    if total_score < 6:
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

    if total_score >= 10:
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

    if total_score >= 6:
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
    """Classify score on 0-14 scale."""
    if score >= 10:
        return "DIA FAVORÁVEL"
    if score >= 6:
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
    if total_score >= 10:
        lines.append("Dia com condições favoráveis para ORB com continuidade.")
    elif total_score >= 6:
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
    max_score: int,
    classification: str,
    direction: str,
    summary: str,
    calendar_data: dict,
    market_data: dict,
    vol_data: dict,
    volume_data: dict,
    trend_data: dict,
    rsi_data: dict,
    asian_data: dict,
    structure_data: dict,
    vix_ts_data: dict,
    bond_data: dict,
    divergence_data: dict,
    seasonality_data: dict,
    currency_data: dict,
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
        "6. SINAIS AVANÇADOS",
    ]

    print()
    print("=" * 64)
    print("   UK100 ORB PRE-OPEN INSTITUTIONAL FILTER")
    print(f"   {now.strftime('%A, %d %B %Y')} — {now.strftime('%H:%M:%S')} (local)")
    print("=" * 64)
    print()

    # Individual module scores
    max_scores = [3, 2, 2, 2, 2, 3]  # Module 1 = 0-3, 2-5 = 0-2, 6 = 0-3
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
    print(f"   Score: {total_score}/{max_score}")
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

    # RSI
    rsi_val = rsi_data.get("rsi")
    rsi_zone = rsi_data.get("zone", "unknown")
    if rsi_val is not None:
        marker = " ⚠" if rsi_zone in ("overbought", "oversold") else ""
        print(f"   RSI FTSE (14d): {rsi_val} [{rsi_zone}]{marker} — {rsi_data.get('detail', '')}")

    # Volume
    vol_trend = volume_data.get("volume_trend", "unknown")
    vol_ratio = volume_data.get("volume_spike_ratio")
    if vol_ratio is not None:
        print(f"   Volume FTSE: {vol_trend} ({vol_ratio:.2f}x média) — {volume_data.get('detail', '')}")

    # Asian session
    a_dir = asian_data.get("direction", "unknown")
    if a_dir not in ("unknown", None):
        nk = asian_data.get("nikkei_pct")
        hs = asian_data.get("hsi_pct")
        parts = []
        if nk is not None:
            parts.append(f"Nikkei {nk:+.2f}%")
        if hs is not None:
            parts.append(f"HSI {hs:+.2f}%")
        asia_str = " | ".join(parts) if parts else "—"
        print(f"   Sessão Asiática: {a_dir} ({asia_str})")

    # Multi-day trend
    t_dir = trend_data.get("direction", "unknown")
    t_cons = trend_data.get("consistency")
    t_mom = trend_data.get("momentum", "?")
    t_days = trend_data.get("days_analysed", 0)
    if t_dir != "unknown" and t_days > 0:
        print(f"   Tendência {t_days}d: {t_dir} | Consistência: {t_cons:.0%} | Momentum: {t_mom}")

    # --- Advanced Signals ---
    print()
    print("   SINAIS AVANÇADOS:")

    # VIX term structure
    vix_struct = vix_ts_data.get("structure", "unknown")
    if vix_struct != "unknown":
        vix_ratio = vix_ts_data.get("ratio", 0)
        vix_sev = vix_ts_data.get("severity", "?")
        print(f"   VIX Term Structure: {vix_struct} ({vix_sev}) — ratio {vix_ratio:.3f}")

    # Bond yield curve
    bond_regime = bond_data.get("regime", "unknown")
    if bond_regime != "unknown":
        spread = bond_data.get("spread", 0)
        print(f"   Yield Curve: {bond_regime} — spread {spread:+.2f}pp")

    # Intermarket divergence
    div_level = divergence_data.get("divergence_level", "unknown")
    if div_level != "unknown":
        agreement = divergence_data.get("daily_agreement", 0)
        print(f"   Divergência Intermercados: {div_level} — concordância diária {agreement:.0%}")

    # Seasonality
    day_name = seasonality_data.get("day_name", "?")
    day_quality = seasonality_data.get("quality", "?")
    day_bias = seasonality_data.get("bias", "?")
    print(f"   Sazonalidade: {day_name} — qualidade ORB: {day_quality} | bias: {day_bias}")

    # Currency strength
    gbp_str = currency_data.get("gbp_strength", "unknown")
    if gbp_str != "unknown":
        print(f"   Força GBP: {gbp_str}")

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
            "volume": volume_data,
            "trend": trend_data,
            "rsi": rsi_data,
            "asian_session": asian_data,
            "structure": structure_data,
            "vix_term_structure": vix_ts_data,
            "bond_yield_curve": bond_data,
            "intermarket_divergence": {
                k: v for k, v in divergence_data.items()
            },
            "seasonality": seasonality_data,
            "currency_strength": currency_data,
            "scores": [
                {"module": section_names[i], "score": s, "detail": d}
                for i, (s, d) in enumerate(scores)
            ],
            "total_score": total_score,
            "max_score": max_score,
            "classification": classification,
            "direction": direction,
        }
        print(json.dumps(raw, indent=2, ensure_ascii=False))


def output_json(
    scores: list[tuple[int, str]],
    total_score: int,
    max_score: int,
    classification: str,
    direction: str,
    summary: str,
    calendar_data: dict,
    market_data: dict,
    vol_data: dict,
    volume_data: dict,
    trend_data: dict,
    rsi_data: dict,
    asian_data: dict,
    structure_data: dict,
    vix_ts_data: dict,
    bond_data: dict,
    divergence_data: dict,
    seasonality_data: dict,
    currency_data: dict,
):
    """Output the analysis as a JSON object."""
    section_names = [
        "macro_events",
        "global_sentiment",
        "correlations",
        "volatility",
        "preopen_structure",
        "advanced_signals",
    ]
    max_per_module = [3, 2, 2, 2, 2, 3]
    result = {
        "timestamp": datetime.now().isoformat(),
        "score": total_score,
        "max_score": max_score,
        "classification": classification,
        "direction": direction,
        "summary": summary,
        "modules": {
            section_names[i]: {"score": s, "max": max_per_module[i], "detail": d}
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
        "volume": {
            k: v for k, v in volume_data.items()
        },
        "trend": {
            k: v for k, v in trend_data.items()
        },
        "rsi": {
            k: v for k, v in rsi_data.items()
        },
        "asian_session": {
            k: v for k, v in asian_data.items()
        },
        "advanced_signals": {
            "vix_term_structure": vix_ts_data,
            "bond_yield_curve": bond_data,
            "intermarket_divergence": {
                k: v for k, v in divergence_data.items()
            },
            "seasonality": seasonality_data,
            "currency_strength": currency_data,
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

def run_analysis(show_raw: bool = False, output_format: str = "text") -> dict:
    """
    Run the complete pre-open analysis pipeline.
    Returns a dict with all results.
    """
    now = datetime.now()

    if output_format == "text":
        print(f"\n  UK100 ORB Pre-Open Filter — a correr às {now.strftime('%H:%M:%S')}")
        print("  A buscar dados reais...\n")

    # 1. Fetch data
    if output_format == "text":
        print("  [1/4] Calendário económico...")
    raw_calendar = fetch_economic_calendar()
    calendar_available = len(raw_calendar) > 0
    calendar_data = filter_events_for_today(raw_calendar, now)
    if not calendar_available:
        calendar_data["calendar_unavailable"] = True

    if output_format == "text":
        print("  [2/4] Dados de mercado (futuros, FX, índices)...")
    market_data = fetch_market_data()

    if output_format == "text":
        print("  [3/4] Volatilidade, volume, RSI, sessão asiática e estrutura pré-abertura...")
    vol_data = compute_ftse_volatility(market_data)
    volume_data = compute_ftse_volume_profile(market_data)
    trend_data = compute_multiday_trend(market_data)
    rsi_data = compute_ftse_rsi(market_data)
    asian_data = compute_asian_session(market_data)
    structure_data = compute_preopen_structure(market_data)

    if output_format == "text":
        print("  [4/4] Sinais avançados (VIX structure, yields, divergência, sazonalidade, FX)...")
    vix_ts_data = compute_vix_term_structure()
    bond_data = compute_bond_yield_curve()
    divergence_data = compute_intermarket_divergence(market_data)
    seasonality_data = compute_seasonality(now)
    currency_data = compute_currency_strength(market_data)

    if output_format == "text":
        print("\n   Dados carregados. A calcular scores...\n")

    # 2. Score all 6 modules
    s1 = score_1_macro_events(calendar_data)
    s2 = score_2_global_sentiment(market_data, asian_data)
    s3 = score_3_correlations(market_data)
    s4 = score_4_volatility(vol_data, market_data, volume_data, rsi_data)
    s5 = score_5_preopen_structure(structure_data, trend_data)
    s6 = score_6_advanced_signals(vix_ts_data, bond_data, divergence_data, seasonality_data, currency_data)

    scores = [s1, s2, s3, s4, s5, s6]
    total_score = sum(s for s, _ in scores)
    max_score = 14  # 3 + 2 + 2 + 2 + 2 + 3

    # 3. Classification + direction
    classification = format_classification(total_score)
    direction = determine_direction(total_score, market_data, calendar_data)

    # 4. Summary
    summary = build_summary(scores, total_score, direction, calendar_data, market_data)

    # 5. Output
    if output_format == "json":
        output_json(
            scores, total_score, max_score, classification, direction, summary,
            calendar_data, market_data, vol_data, volume_data, trend_data, rsi_data, asian_data, structure_data,
            vix_ts_data, bond_data, divergence_data, seasonality_data, currency_data,
        )
    else:
        print_full_output(
            scores, total_score, max_score, classification, direction, summary,
            calendar_data, market_data, vol_data, volume_data, trend_data, rsi_data, asian_data, structure_data,
            vix_ts_data, bond_data, divergence_data, seasonality_data, currency_data,
            show_raw=show_raw,
        )

    # 6. Save last analysis to JSON file for potential dashboard/telegram use
    result = {
        "timestamp": now.isoformat(),
        "mode": "rule-based",
        "score": total_score,
        "max_score": max_score,
        "classification": classification,
        "direction": direction,
        "summary": summary,
    }
    try:
        with open("last_analysis.json", "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # non-critical

    # 7. Append to session log (accuracy tracking over time)
    log_entry = {
        "timestamp": now.isoformat(),
        "score": total_score,
        "max_score": max_score,
        "classification": classification,
        "direction": direction,
        "modules": {
            "macro": scores[0][0],
            "sentiment": scores[1][0],
            "correlations": scores[2][0],
            "volatility": scores[3][0],
            "structure": scores[4][0],
            "advanced": scores[5][0],
        },
        "rsi": rsi_data.get("rsi"),
        "asian_direction": asian_data.get("direction"),
        "volume_trend": volume_data.get("volume_trend"),
        "trend_direction": trend_data.get("direction"),
        "vix_structure": vix_ts_data.get("structure"),
        "bond_regime": bond_data.get("regime"),
        "divergence_level": divergence_data.get("divergence_level"),
        "gbp_strength": currency_data.get("gbp_strength"),
    }
    try:
        with open(ANALYSIS_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass  # non-critical

    return result


def main():
    parser = argparse.ArgumentParser(
        description="UK100 ORB Pre-Open Institutional Filter — CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python uk100_orb_filter.py             # Full analysis
  python uk100_orb_filter.py --raw       # Analysis + raw data debug
  python uk100_orb_filter.py --json      # Output as JSON
  python uk100_orb_filter.py --history   # Show last 10 analysis entries
  python uk100_orb_filter.py --history 20  # Show last 20 entries
        """,
    )
    parser.add_argument(
        "--raw", action="store_true",
        help="Print raw fetched data at the end (debug)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output result as JSON (machine-readable)",
    )
    parser.add_argument(
        "--history", nargs="?", const=10, type=int, metavar="N",
        help="Show last N entries from the session log (default: 10)",
    )
    args = parser.parse_args()

    if args.history is not None:
        _print_history(args.history)
        return

    output_format = "json" if args.json else "text"
    run_analysis(show_raw=args.raw, output_format=output_format)


def _print_history(n: int = 10):
    """Print the last N entries from analysis_log.jsonl."""
    if not ANALYSIS_LOG_FILE.exists():
        print("Nenhum histórico encontrado. Execute a ferramenta primeiro.")
        return

    try:
        lines = ANALYSIS_LOG_FILE.read_text(encoding="utf-8").strip().splitlines()
    except Exception as e:
        print(f"Erro ao ler histórico: {e}")
        return

    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except Exception:
            pass

    entries = entries[-n:]

    print()
    print("=" * 64)
    print(f"   HISTÓRICO DE ANÁLISES — últimas {len(entries)} entradas")
    print("=" * 64)
    for e in entries:
        ts = e.get("timestamp", "?")[:16].replace("T", " ")
        score = e.get("score", "?")
        mx = e.get("max_score", 11)  # backward compat with old entries
        cls = e.get("classification", "?")
        direction = e.get("direction", "?")
        asian = e.get("asian_direction", "?")
        rsi = e.get("rsi")
        rsi_str = f"  RSI:{rsi}" if rsi is not None else ""
        vix_s = e.get("vix_structure")
        vix_str = f"  VIX:{vix_s}" if vix_s else ""
        print(f"  {ts}  {score:>2}/{mx}  {cls:<22}  {direction:<12}  Ásia:{asian}{rsi_str}{vix_str}")
    print("=" * 64)
    print()


if __name__ == "__main__":
    main()
