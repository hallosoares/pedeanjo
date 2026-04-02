"""
Intermarket Divergence — detect when FTSE decouples from peers.

When DAX rises but FTSE doesn't follow (or vice-versa), something is
brewing. Same with SPX vs FTSE. Divergences often precede sharp moves
as the "lagging" index plays catch-up.

Method:
- Compare multi-day returns (5-day) of FTSE vs DAX and FTSE vs SPX
- If they usually move together but recently diverged → alert
- Compute direction agreement over the last N days

For ORB context:
- Convergence = markets aligned, cleaner breakouts
- Divergence = dislocation, breakout direction less certain but
  mean-reversion trades can be high-probability
"""

from __future__ import annotations


def compute_intermarket_divergence(market_data: dict) -> dict:
    """
    Compare FTSE vs DAX and FTSE vs SPX multi-day price action.
    Uses the DataFrame already fetched in market_data (no extra API calls).

    Parameters
    ----------
    market_data : dict
        From fetch_market_data(), must contain FTSE, DAX, SPX_futures
        with 'df' key holding the price DataFrame.

    Returns
    -------
    dict with keys:
        ftse_vs_dax     : dict with pct_ftse, pct_dax, gap, aligned (bool)
        ftse_vs_spx     : dict with pct_ftse, pct_spx, gap, aligned (bool)
        daily_agreement : float (0.0–1.0, fraction of days FTSE and peers move same direction)
        divergence_level: "none" | "mild" | "notable" | "strong"
        score_hint      : int (+1 aligned, 0 mild, -1 divergent)
        detail          : str (human-readable, Portuguese)
    """
    base = {
        "ftse_vs_dax": None,
        "ftse_vs_spx": None,
        "daily_agreement": None,
        "divergence_level": "unknown",
        "score_hint": 0,
        "detail": "Dados insuficientes para análise de divergência intermercados.",
    }

    ftse_df = _get_df(market_data, "FTSE")
    dax_df = _get_df(market_data, "DAX")
    spx_df = _get_df(market_data, "SPX_futures")

    if ftse_df is None or len(ftse_df) < 3:
        return base

    # --- Multi-day return comparison ---
    ftse_closes = ftse_df["Close"].dropna().tolist()
    n = min(len(ftse_closes), 10)  # use up to 10 days
    if n < 3:
        return base

    ftse_ret_total = (ftse_closes[-1] - ftse_closes[-n]) / ftse_closes[-n] * 100

    comparisons = {}
    agreement_counts = []

    for label, peer_key in [("DAX", "DAX"), ("SPX", "SPX_futures")]:
        peer_df = _get_df(market_data, peer_key)
        if peer_df is None or len(peer_df) < 3:
            comparisons[label] = None
            continue

        peer_closes = peer_df["Close"].dropna().tolist()
        m = min(len(peer_closes), n)
        if m < 3:
            comparisons[label] = None
            continue

        peer_ret_total = (peer_closes[-1] - peer_closes[-m]) / peer_closes[-m] * 100
        gap = round(ftse_ret_total - peer_ret_total, 2)

        # Daily direction agreement (last m days)
        ftse_recent = ftse_closes[-m:]
        peer_recent = peer_closes[-m:]
        agree = 0
        total = 0
        for i in range(1, min(len(ftse_recent), len(peer_recent))):
            f_dir = ftse_recent[i] - ftse_recent[i - 1]
            p_dir = peer_recent[i] - peer_recent[i - 1]
            if (f_dir > 0 and p_dir > 0) or (f_dir < 0 and p_dir < 0):
                agree += 1
            total += 1

        daily_agree_pct = agree / total if total > 0 else 0.5
        agreement_counts.append(daily_agree_pct)

        aligned = abs(gap) < 1.5  # within 1.5pp = aligned

        comparisons[label] = {
            f"pct_ftse": round(ftse_ret_total, 2),
            f"pct_{label.lower()}": round(peer_ret_total, 2),
            "gap": gap,
            "aligned": aligned,
            "daily_agreement": round(daily_agree_pct, 2),
        }

    # --- Overall divergence assessment ---
    available = {k: v for k, v in comparisons.items() if v is not None}
    if not available:
        return base

    avg_agreement = sum(agreement_counts) / len(agreement_counts) if agreement_counts else 0.5
    gaps = [abs(v["gap"]) for v in available.values()]
    max_gap = max(gaps)

    if max_gap < 1.0 and avg_agreement >= 0.65:
        level = "none"
        hint = 1
        detail_parts = [f"FTSE vs {k}: gap {v['gap']:+.2f}pp" for k, v in available.items()]
        detail = (
            f"Mercados alinhados ({', '.join(detail_parts)}). "
            f"Concordância diária: {avg_agreement:.0%}. "
            f"Breakouts mais fiáveis."
        )
    elif max_gap < 2.5 and avg_agreement >= 0.45:
        level = "mild"
        hint = 0
        detail_parts = [f"FTSE vs {k}: gap {v['gap']:+.2f}pp" for k, v in available.items()]
        detail = (
            f"Divergência leve ({', '.join(detail_parts)}). "
            f"Concordância diária: {avg_agreement:.0%}. "
            f"Sem alarme, mas monitorizar."
        )
    elif max_gap < 4.0:
        level = "notable"
        hint = -1
        detail_parts = [f"FTSE vs {k}: gap {v['gap']:+.2f}pp" for k, v in available.items()]
        detail = (
            f"Divergência notável ({', '.join(detail_parts)}). "
            f"Concordância diária: {avg_agreement:.0%}. "
            f"FTSE pode estar a atrasar ou a antecipar — cuidado com direção."
        )
    else:
        level = "strong"
        hint = -1
        detail_parts = [f"FTSE vs {k}: gap {v['gap']:+.2f}pp" for k, v in available.items()]
        detail = (
            f"Divergência forte ({', '.join(detail_parts)}). "
            f"Concordância diária: {avg_agreement:.0%}. "
            f"Dislocation — breakout pode reverter rapidamente."
        )

    return {
        "ftse_vs_dax": comparisons.get("DAX"),
        "ftse_vs_spx": comparisons.get("SPX"),
        "daily_agreement": round(avg_agreement, 2),
        "divergence_level": level,
        "score_hint": hint,
        "detail": detail,
    }


def _get_df(market_data: dict, key: str):
    """Safely extract DataFrame from market_data."""
    data = market_data.get(key, {})
    if data is None:
        return None
    return data.get("df")
