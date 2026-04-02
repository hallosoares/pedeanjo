"""
Currency Strength — GBP relative strength vs basket.

Instead of just GBPUSD, we measure GBP against multiple currencies:
- GBPUSD (already in main tool — we use market_data)
- GBPJPY (risk barometer: JPY is safe-haven)
- GBPCHF (risk barometer: CHF is safe-haven)
- EURGBP (inverse: falling EURGBP = GBP strength)

When GBP is strong across ALL pairs → risk-on for FTSE, stronger
breakout conviction. When GBP is weak across all → risk-off headwind.
Divergence between pairs = mixed signal.

For ORB context:
- GBP strong = tailwind for FTSE long breakouts
- GBP weak   = tailwind for FTSE short breakouts
- Mixed      = less conviction in breakout direction
"""

from __future__ import annotations

import sys

import yfinance as yf

# Extra pairs not in main TICKERS — we fetch these ourselves
_EXTRA_PAIRS = {
    "GBPJPY": "GBPJPY=X",
    "GBPCHF": "GBPCHF=X",
    "EURGBP": "EURGBP=X",
}


def compute_currency_strength(market_data: dict) -> dict:
    """
    Compute GBP relative strength across a basket of pairs.

    Parameters
    ----------
    market_data : dict
        From fetch_market_data(), must contain GBPUSD with 'pct_change'.

    Returns
    -------
    dict with keys:
        pairs         : dict of pair_name -> pct_change
        gbp_moves     : int  (how many pairs show GBP strength)
        gbp_strength  : "strong" | "moderate" | "weak" | "mixed" | "unknown"
        score_hint    : int (+1 strong, 0 mixed, -1 weak)
        detail        : str (human-readable, Portuguese)
    """
    base = {
        "pairs": {},
        "gbp_moves": 0,
        "gbp_strength": "unknown",
        "score_hint": 0,
        "detail": "Dados de moedas insuficientes para avaliar força da GBP.",
    }

    # Get GBPUSD from existing market_data (no extra API call)
    pairs = {}
    gbpusd_data = market_data.get("GBPUSD", {})
    if gbpusd_data and gbpusd_data.get("pct_change") is not None:
        pairs["GBPUSD"] = gbpusd_data["pct_change"]

    # Fetch extra pairs
    for label, symbol in _EXTRA_PAIRS.items():
        pct = _fetch_pct_change(symbol)
        if pct is not None:
            pairs[label] = pct

    if len(pairs) < 2:
        return base

    # For EURGBP, invert: if EURGBP falls, GBP is stronger
    gbp_strong_count = 0
    gbp_weak_count = 0
    detail_parts = []

    for pair, pct in pairs.items():
        if pair == "EURGBP":
            # Inverse pair: EURGBP down = GBP strong
            effective = -pct
            detail_parts.append(f"EUR/GBP {pct:+.2f}% (inv: {effective:+.2f}%)")
        else:
            effective = pct
            detail_parts.append(f"{pair} {pct:+.2f}%")

        if effective > 0.10:
            gbp_strong_count += 1
        elif effective < -0.10:
            gbp_weak_count += 1

    total = len(pairs)

    if gbp_strong_count >= total * 0.75:
        strength = "strong"
        hint = 1
        summary = (
            f"GBP forte contra o basket ({gbp_strong_count}/{total} pares positivos). "
            f"Tailwind para FTSE longs."
        )
    elif gbp_strong_count >= total * 0.5:
        strength = "moderate"
        hint = 1
        summary = (
            f"GBP moderadamente forte ({gbp_strong_count}/{total} pares positivos). "
            f"Leve suporte para FTSE."
        )
    elif gbp_weak_count >= total * 0.75:
        strength = "weak"
        hint = -1
        summary = (
            f"GBP fraca contra o basket ({gbp_weak_count}/{total} pares negativos). "
            f"Headwind para FTSE longs, favorecer shorts."
        )
    elif gbp_weak_count >= total * 0.5:
        strength = "moderate_weak"
        hint = -1
        summary = (
            f"GBP moderadamente fraca ({gbp_weak_count}/{total} pares negativos). "
            f"Algum headwind para FTSE."
        )
    else:
        strength = "mixed"
        hint = 0
        summary = (
            f"GBP mista ({gbp_strong_count} forte, {gbp_weak_count} fraca de {total}). "
            f"Sem viés claro de moeda."
        )

    detail = f"{summary} | {', '.join(detail_parts)}"

    return {
        "pairs": pairs,
        "gbp_moves": gbp_strong_count,
        "gbp_strength": strength,
        "score_hint": hint,
        "detail": detail,
    }


def _fetch_pct_change(symbol: str) -> float | None:
    """Fetch last day's pct change for a yfinance symbol."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="5d", interval="1d")
        if df.empty or len(df) < 2:
            return None
        last = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2])
        if prev == 0:
            return None
        return round((last - prev) / prev * 100, 3)
    except Exception as e:
        print(f"    Currency strength: {symbol} fetch failed: {e}", file=sys.stderr)
        return None
