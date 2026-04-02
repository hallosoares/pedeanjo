"""
Day-of-Week Seasonality — FTSE 100 ORB historical patterns.

Based on documented and backtested FTSE 100 intraday patterns:

Monday:
- Tends to gap from weekend news, but ORB breakouts often reverse
  (weekend positioning unwinds). Higher fakeout rate.
- Mean-reversion bias rather than trend.

Tuesday:
- Often continues Monday's direction if Monday established a clear trend.
- Moderate reliability for ORB.

Wednesday:
- Historically the strongest trend day for FTSE 100 and US markets.
- ORB breakouts have highest follow-through probability mid-week.
- Institutional flow highest on Wednesdays (portfolio adjustments).

Thursday:
- Pre-Friday positioning begins. Can be continuation or reversal of
  mid-week trend depending on economic calendar.
- Moderate reliability.

Friday:
- Profit-taking and position squaring before weekend.
- Reduced conviction, tighter ranges. ORB less reliable.
- "Never trade the ORB on Friday afternoon" — classic prop desk rule.

Sources: Multiple FTSE 100 backtests, London session statistics,
prop firm trading guidelines.
"""

from __future__ import annotations

from datetime import datetime


# Day-of-week profiles: (bias, quality, score_hint, note)
# bias: "trend" = breakout likely holds, "reversion" = breakout may reverse
# quality: "high" / "moderate" / "low" = ORB reliability
_DAY_PROFILES = {
    0: {  # Monday
        "day_name": "Segunda-feira",
        "bias": "reversion",
        "quality": "low",
        "score_hint": -1,
        "note": (
            "Segundas: gap de fim-de-semana frequente, ORB propenso a reversão. "
            "Posicionamento de fim-de-semana a ser desfeito. Fakeout rate elevado."
        ),
    },
    1: {  # Tuesday
        "day_name": "Terça-feira",
        "bias": "continuation",
        "quality": "moderate",
        "score_hint": 0,
        "note": (
            "Terças: frequentemente continua a direção de segunda se houve tendência clara. "
            "Fiabilidade moderada para ORB."
        ),
    },
    2: {  # Wednesday
        "day_name": "Quarta-feira",
        "bias": "trend",
        "quality": "high",
        "score_hint": 1,
        "note": (
            "Quartas: historicamente o melhor dia de tendência para FTSE e mercados globais. "
            "Fluxo institucional elevado — breakouts com maior probabilidade de continuidade."
        ),
    },
    3: {  # Thursday
        "day_name": "Quinta-feira",
        "bias": "mixed",
        "quality": "moderate",
        "score_hint": 0,
        "note": (
            "Quintas: posicionamento pré-sexta pode criar continuidade ou reversão. "
            "Dependente do calendário económico. Fiabilidade moderada."
        ),
    },
    4: {  # Friday
        "day_name": "Sexta-feira",
        "bias": "reversion",
        "quality": "low",
        "score_hint": -1,
        "note": (
            "Sextas: profit-taking e square de posições antes do fim-de-semana. "
            "Ranges mais apertados, menor convicção. ORB menos fiável."
        ),
    },
}


def compute_seasonality(ref_date: datetime | None = None) -> dict:
    """
    Determine ORB quality bias based on day of the week.

    Parameters
    ----------
    ref_date : datetime, optional
        Date to check. Defaults to now.

    Returns
    -------
    dict with keys:
        day_of_week   : int (0=Mon, 6=Sun)
        day_name      : str (Portuguese)
        bias          : "trend" | "reversion" | "continuation" | "mixed"
        quality       : "high" | "moderate" | "low"
        score_hint    : int (+1 trend day, 0 moderate, -1 low quality)
        detail        : str (human-readable, Portuguese)
    """
    if ref_date is None:
        ref_date = datetime.now()

    dow = ref_date.weekday()  # 0=Mon, 6=Sun

    if dow in _DAY_PROFILES:
        profile = _DAY_PROFILES[dow]
        return {
            "day_of_week": dow,
            "day_name": profile["day_name"],
            "bias": profile["bias"],
            "quality": profile["quality"],
            "score_hint": profile["score_hint"],
            "detail": profile["note"],
        }

    # Weekend — shouldn't happen in normal trading, but handle gracefully
    return {
        "day_of_week": dow,
        "day_name": "Fim-de-semana",
        "bias": "none",
        "quality": "none",
        "score_hint": 0,
        "detail": "Fim-de-semana — mercados fechados.",
    }
