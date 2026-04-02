"""
Bond Yield Curve — US 2Y/10Y spread as risk regime detector.

The spread between US 10-year and 2-year Treasury yields is one of the
most reliable recession / risk-off indicators:
- Normal (10Y > 2Y, spread > 0): growth expected, risk-on
- Flat (spread near 0): uncertainty, transition
- Inverted (10Y < 2Y, spread < 0): recession risk, risk-off

For ORB context:
- Normal/steep curve: orderly markets, breakouts more reliable
- Flat: less conviction, mixed signals
- Inverted: risk-off regime, defensive positioning dominates,
  breakouts less reliable (except in momentum sell-offs)
"""

from __future__ import annotations

import sys

import yfinance as yf

# ^TNX = 10-year yield (in %), 2YY=F = 2-year yield future
# ^IRX = 13-week T-bill (close proxy for short end, more data)
TICKER_10Y = "^TNX"
TICKER_2Y = "2YY=F"
TICKER_2Y_FALLBACK = "^IRX"  # 13-week as fallback


def compute_bond_yield_curve() -> dict:
    """
    Fetch US 2Y and 10Y yields, compute spread.

    Returns
    -------
    dict with keys:
        yield_10y     : float | None  (in %)
        yield_2y      : float | None  (in %)
        spread        : float | None  (10Y - 2Y, in percentage points)
        is_inverted   : bool | None
        regime        : "normal" | "flat" | "inverted" | "unknown"
        score_hint    : int  (+1 normal, 0 flat, -1 inverted)
        detail        : str  (human-readable, Portuguese)
    """
    base = {
        "yield_10y": None,
        "yield_2y": None,
        "spread": None,
        "is_inverted": None,
        "regime": "unknown",
        "score_hint": 0,
        "detail": "Dados da curva de yields indisponíveis.",
    }

    y10 = _fetch_last_close(TICKER_10Y)
    y2 = _fetch_last_close(TICKER_2Y)

    # Fallback to 13-week T-bill if 2Y futures unavailable
    if y2 is None:
        y2 = _fetch_last_close(TICKER_2Y_FALLBACK)

    if y10 is None or y2 is None:
        return base

    spread = round(y10 - y2, 3)
    is_inverted = spread < 0

    if spread > 0.50:
        regime = "normal"
        hint = 1
        detail = (
            f"Curva de yields normal (10Y {y10:.2f}% vs 2Y {y2:.2f}%, "
            f"spread +{spread:.2f}pp). Mercado espera crescimento — "
            f"ambiente favorece breakouts."
        )
    elif spread > 0.10:
        regime = "normal"
        hint = 1
        detail = (
            f"Curva de yields levemente positiva (10Y {y10:.2f}% vs 2Y {y2:.2f}%, "
            f"spread +{spread:.2f}pp). Sem alarme."
        )
    elif spread > -0.10:
        regime = "flat"
        hint = 0
        detail = (
            f"Curva de yields flat (10Y {y10:.2f}% vs 2Y {y2:.2f}%, "
            f"spread {spread:+.2f}pp). Zona de incerteza — sem viés claro."
        )
    elif spread > -0.50:
        regime = "inverted"
        hint = -1
        detail = (
            f"Curva de yields invertida (10Y {y10:.2f}% vs 2Y {y2:.2f}%, "
            f"spread {spread:+.2f}pp). Sinal de recessão — "
            f"mercado defensivo, breakouts menos fiáveis."
        )
    else:
        regime = "inverted"
        hint = -1
        detail = (
            f"Curva de yields profundamente invertida (10Y {y10:.2f}% vs 2Y {y2:.2f}%, "
            f"spread {spread:+.2f}pp). Forte sinal de recessão — "
            f"cautela máxima."
        )

    return {
        "yield_10y": y10,
        "yield_2y": y2,
        "spread": spread,
        "is_inverted": is_inverted,
        "regime": regime,
        "score_hint": hint,
        "detail": detail,
    }


def _fetch_last_close(symbol: str) -> float | None:
    """Fetch last closing price for a yfinance symbol."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(period="5d", interval="1d")
        if df.empty or len(df) < 1:
            return None
        return round(float(df["Close"].iloc[-1]), 4)
    except Exception as e:
        print(f"    Bond yield curve: {symbol} fetch failed: {e}", file=sys.stderr)
        return None
