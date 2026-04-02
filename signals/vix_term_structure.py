"""
VIX Term Structure — contango vs backwardation detection.

Compares VIX spot (^VIX) with VIX 3-month (^VIX3M).
- Contango  (VIX < VIX3M): market is calm, normal state.
- Flat      (VIX ≈ VIX3M): transition zone, uncertainty.
- Backwardation (VIX > VIX3M): market is panicking, near-term fear
  exceeds longer-term → historically precedes large moves / sell-offs.

For ORB context:
- Contango = orderly breakouts, higher follow-through probability
- Backwardation = chaotic, fakeout-prone, but BIG moves if right
"""

from __future__ import annotations

import sys

import yfinance as yf


def compute_vix_term_structure() -> dict:
    """
    Fetch VIX spot and VIX3M, compute term structure.

    Returns
    -------
    dict with keys:
        vix_spot      : float | None
        vix_3m        : float | None
        ratio         : float | None  (spot / 3m; <1 = contango, >1 = backwardation)
        structure     : "contango" | "backwardation" | "flat" | "unknown"
        severity      : "deep" | "moderate" | "mild" | "unknown"
        score_hint    : int  (+1 calm/contango, 0 flat, -1 backwardation)
        detail        : str  (human-readable, Portuguese)
    """
    base = {
        "vix_spot": None,
        "vix_3m": None,
        "ratio": None,
        "structure": "unknown",
        "severity": "unknown",
        "score_hint": 0,
        "detail": "Dados da estrutura temporal do VIX indisponíveis.",
    }

    vix_spot = _fetch_last_close("^VIX")
    vix_3m = _fetch_last_close("^VIX3M")

    if vix_spot is None or vix_3m is None or vix_3m == 0:
        return base

    ratio = round(vix_spot / vix_3m, 3)

    if ratio < 0.90:
        structure = "contango"
        severity = "deep"
        hint = 1
        detail = (
            f"VIX em contango profundo (spot {vix_spot:.1f} vs 3M {vix_3m:.1f}, "
            f"ratio {ratio:.3f}). Mercado calmo — breakouts com boa continuidade."
        )
    elif ratio < 0.97:
        structure = "contango"
        severity = "moderate"
        hint = 1
        detail = (
            f"VIX em contango moderado (spot {vix_spot:.1f} vs 3M {vix_3m:.1f}, "
            f"ratio {ratio:.3f}). Estrutura normal — favorece breakouts."
        )
    elif ratio <= 1.03:
        structure = "flat"
        severity = "mild"
        hint = 0
        detail = (
            f"VIX flat (spot {vix_spot:.1f} vs 3M {vix_3m:.1f}, "
            f"ratio {ratio:.3f}). Zona de transição — sem viés claro."
        )
    elif ratio <= 1.10:
        structure = "backwardation"
        severity = "moderate"
        hint = -1
        detail = (
            f"VIX em backwardation moderada (spot {vix_spot:.1f} vs 3M {vix_3m:.1f}, "
            f"ratio {ratio:.3f}). Medo de curto prazo elevado — cuidado com fakeouts."
        )
    else:
        structure = "backwardation"
        severity = "deep"
        hint = -1
        detail = (
            f"VIX em backwardation profunda (spot {vix_spot:.1f} vs 3M {vix_3m:.1f}, "
            f"ratio {ratio:.3f}). Pânico de mercado — alta probabilidade de movimentos "
            f"extremos. Fakeouts prováveis."
        )

    return {
        "vix_spot": vix_spot,
        "vix_3m": vix_3m,
        "ratio": ratio,
        "structure": structure,
        "severity": severity,
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
        return round(float(df["Close"].iloc[-1]), 2)
    except Exception as e:
        print(f"    VIX term structure: {symbol} fetch failed: {e}", file=sys.stderr)
        return None
