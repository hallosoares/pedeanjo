"""
signals — Advanced signal modules for UK100 ORB Pre-Open Filter.

Each module exposes a single `compute_*()` function that accepts
market_data (and optional extras) and returns a standardised dict with:
    - One or more analytic fields
    - score_hint: int  (+1 / 0 / -1)
    - detail: str      (human-readable, Portuguese)
"""

from signals.vix_term_structure import compute_vix_term_structure
from signals.bond_yield_curve import compute_bond_yield_curve
from signals.intermarket_divergence import compute_intermarket_divergence
from signals.seasonality import compute_seasonality
from signals.currency_strength import compute_currency_strength

__all__ = [
    "compute_vix_term_structure",
    "compute_bond_yield_curve",
    "compute_intermarket_divergence",
    "compute_seasonality",
    "compute_currency_strength",
]
