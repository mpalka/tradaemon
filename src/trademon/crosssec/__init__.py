"""Cross-sectional ranking research module (module 3).

Instead of asking "will BTC go up?" (module 1's hypothesis, which measured out at
roughly zero edge across eight iterations), this asks "which assets are strongest
*relative to each other*?" — buy the leaders, optionally sell the laggards. The bet
is on the spread between assets rather than on market direction.

Research-only: this module measures a hypothesis, it does not run a live book. The
long-short variant is not executable on spot at all (it needs perpetuals), so the
backtest models costs as turnover x cost rate rather than per-order fills.
"""
