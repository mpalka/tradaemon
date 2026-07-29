"""The ranking signal: pure functions, no I/O, no look-ahead.

Every function here takes price history that ends at the decision date and returns
what to hold from the *next* bar onward. Nothing reads a price it could not have
known at decision time — the property the tests pin down.
"""

from __future__ import annotations

import pandas as pd


def momentum_scores(history: pd.DataFrame, lookback_days: int,
                    skip_days: int = 0) -> pd.Series:
    """Relative strength per asset at the end of `history`.

    The score is the return from `lookback_days` ago up to `skip_days` ago, so the
    freshest bars are deliberately excluded: very recent moves tend to mean-revert,
    and counting them blends a reversal effect into a momentum signal.

    Returns a Series indexed by symbol, NaN for names without enough history.
    """
    need = lookback_days + skip_days + 1
    if len(history) < need:
        return pd.Series(dtype="float64")
    end = history.iloc[-1 - skip_days]          # price `skip_days` ago
    start = history.iloc[-1 - skip_days - lookback_days]
    scores = (end / start) - 1.0
    return scores.replace([float("inf"), float("-inf")], pd.NA).dropna().astype("float64")


def select_legs(scores: pd.Series, n_long: int,
                n_short: int = 0) -> tuple[list[str], list[str]]:
    """Strongest `n_long` and weakest `n_short` names by score.

    The legs are trimmed so they never overlap: with a thin universe, asking for
    5 + 5 out of 8 names would otherwise buy and sell the same asset.
    """
    ranked = scores.sort_values(ascending=False)
    if ranked.empty:
        return [], []
    n_long = max(0, min(n_long, len(ranked)))
    n_short = max(0, min(n_short, len(ranked) - n_long))
    longs = list(ranked.index[:n_long])
    shorts = list(ranked.index[len(ranked) - n_short:]) if n_short else []
    return longs, shorts


def target_weights(longs: list[str], shorts: list[str],
                   direction: str = "long_short") -> dict[str, float]:
    """Equal-weight target book from the two legs.

    long_only: the long leg splits 100% of capital.
    long_short: +50% spread across the leaders and -50% across the laggards, so gross
    exposure is 100% and net exposure is ~0 — the bet is on the *spread* between the
    legs, not on the market going up.
    """
    if direction == "long_only":
        return {s: 1.0 / len(longs) for s in longs} if longs else {}
    if direction != "long_short":
        raise ValueError(f"unknown direction {direction!r}")
    weights: dict[str, float] = {}
    if longs:
        weights.update({s: 0.5 / len(longs) for s in longs})
    if shorts:
        weights.update({s: -0.5 / len(shorts) for s in shorts})
    return weights


def weights_at(history: pd.DataFrame, lookback_days: int, skip_days: int,
               n_long: int, n_short: int, direction: str) -> dict[str, float]:
    """Full signal chain for one decision date: score -> legs -> target weights.

    `history` must end at the decision bar; the result applies from the next bar.
    """
    scores = momentum_scores(history, lookback_days, skip_days)
    if scores.empty:
        return {}
    longs, shorts = select_legs(scores, n_long, n_short if direction == "long_short" else 0)
    return target_weights(longs, shorts, direction)
