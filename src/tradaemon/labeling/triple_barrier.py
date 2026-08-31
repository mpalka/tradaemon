"""Triple-barrier labeling (Lopez de Prado) matched to the execution model.

For a signal at the close of bar t the position is entered at the open of
bar t+1; barriers are entry +/- mult * ATR(t). We then scan bars t+1..t+H:
label 1 iff the take-profit barrier is touched strictly before the stop-loss
barrier. A bar touching both barriers counts as stop-loss (conservative),
same as the fill simulator in tradaemon.execution.fills.

direction="long": take-profit is above entry (bet on price up), stop below.
direction="short": mirror image — take-profit is below entry (bet on price
down), stop above. The short label answers "does a down-move of tp_mult*ATR
happen before an up-move of sl_mult*ATR", enabling a symmetric short model.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd


def triple_barrier_labels(
    df: pd.DataFrame,
    atr: pd.Series,
    tp_mult: float,
    sl_mult: float,
    horizon: int,
    direction: Literal["long", "short"] = "long",
) -> pd.DataFrame:
    n = len(df)
    high = df["high"].to_numpy(float)
    low = df["low"].to_numpy(float)
    open_ = df["open"].to_numpy(float)
    atr_v = atr.to_numpy(float)

    entry = np.roll(open_, -1)  # open of bar t+1
    entry[-1] = np.nan
    if direction == "long":
        tp_price = entry + tp_mult * atr_v  # profit when price rises to here
        sl_price = entry - sl_mult * atr_v  # loss when price falls to here
    else:
        tp_price = entry - tp_mult * atr_v  # profit when price falls to here
        sl_price = entry + sl_mult * atr_v  # loss when price rises to here

    first_tp = np.full(n, np.inf)
    first_sl = np.full(n, np.inf)
    for k in range(horizon):
        shift = k + 1  # bar t+1+k
        h_k = np.full(n, -np.inf)
        l_k = np.full(n, np.inf)
        if shift < n:
            h_k[: n - shift] = high[shift:]
            l_k[: n - shift] = low[shift:]
        if direction == "long":
            tp_hit, sl_hit = h_k >= tp_price, l_k <= sl_price
        else:
            tp_hit, sl_hit = l_k <= tp_price, h_k >= sl_price
        first_tp = np.where(np.isinf(first_tp) & tp_hit, k, first_tp)
        first_sl = np.where(np.isinf(first_sl) & sl_hit, k, first_sl)

    label = (first_tp < first_sl).astype(float)  # tie -> SL wins -> 0
    hit_step = np.where(label == 1.0, first_tp, first_sl)
    hit_step = np.where(np.isinf(hit_step), np.nan, hit_step)

    # Bars without a full horizon of future data (or without valid barriers)
    # cannot be labeled.
    valid = np.ones(n, dtype=bool)
    valid[max(0, n - horizon - 1):] = False
    valid &= ~np.isnan(entry) & ~np.isnan(atr_v) & (atr_v > 0)
    label = np.where(valid, label, np.nan)

    return pd.DataFrame(
        {
            "label": label,
            "entry_price": entry,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "hit_step": hit_step,
        },
        index=df.index,
    )
