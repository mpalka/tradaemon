"""Free daily ETF/stock data. No API key, no extra dependency (stdlib only).

Primary source: the Yahoo Finance chart API (keyless JSON), e.g.
https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=max&interval=1d
Yahoo tickers are the plain symbol (SPY, TLT, GLD). We store the data in the same
Parquet layout as crypto (source id "yahoo") and expose an aligned close-price panel
for the allocator and backtest.

(Stooq was the original choice but now gates its CSV behind a JavaScript bot-check,
so it can't be fetched headlessly; `parse_stooq_csv` is kept for manual CSV imports.)
"""

from __future__ import annotations

import io
import json
import logging
import time
import urllib.request
from pathlib import Path

import pandas as pd

from tradaemon.data import storage

log = logging.getLogger(__name__)

# period1/period2 (not range=max) — range=max silently returns MONTHLY bars; an
# explicit epoch window keeps interval=1d honest and gives full daily history.
YAHOO_URL = ("https://query1.finance.yahoo.com/v8/finance/chart/"
             "{ticker}?period1={p1}&period2={p2}&interval=1d")
TIMEFRAME = "1d"
SOURCE_ID = "yahoo"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}


def parse_yahoo_chart(payload: dict) -> pd.DataFrame:
    """Parse a Yahoo chart JSON payload into the OHLCV schema (daily, UTC dates)."""
    chart = payload.get("chart", {})
    if chart.get("error"):
        raise RuntimeError(f"Yahoo error: {chart['error']}")
    results = chart.get("result")
    if not results:
        raise RuntimeError("Yahoo returned no result")
    res = results[0]
    ts = res.get("timestamp") or []
    quote = res["indicators"]["quote"][0]
    n = len(ts)
    out = pd.DataFrame({
        # daily bars are stamped at market open; normalize to the UTC date key
        "timestamp": pd.to_datetime(ts, unit="s", utc=True).normalize(),
        "open": quote.get("open") or [None] * n,
        "high": quote.get("high") or [None] * n,
        "low": quote.get("low") or [None] * n,
        "close": quote.get("close") or [None] * n,
        "volume": quote.get("volume") or [0] * n,
    })
    return out.dropna(subset=["close"]).astype(
        {c: "float64" for c in ["open", "high", "low", "close", "volume"]}
    ).reset_index(drop=True)


def parse_stooq_csv(text: str) -> pd.DataFrame:
    """Parse a Stooq daily CSV (Date,Open,High,Low,Close[,Volume]) for manual imports."""
    df = pd.read_csv(io.StringIO(text)).rename(columns=str.lower)
    if "date" not in df.columns or df.empty:
        raise RuntimeError(f"unexpected CSV: {text[:120]!r}")
    out = pd.DataFrame({
        "timestamp": pd.to_datetime(df["date"], utc=True),
        "open": df["open"].astype("float64"),
        "high": df["high"].astype("float64"),
        "low": df["low"].astype("float64"),
        "close": df["close"].astype("float64"),
        "volume": df["volume"].astype("float64") if "volume" in df else 0.0,
    })
    return out.dropna(subset=["close"]).reset_index(drop=True)


def _fetch_chart(ticker: str, timeout: float = 30.0) -> dict:
    p2 = int(time.time()) + 86_400  # a little past 'now' to include the latest bar
    req = urllib.request.Request(
        YAHOO_URL.format(ticker=ticker, p1=0, p2=p2), headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def path_for(data_dir: Path, symbol: str) -> Path:
    return storage.ohlcv_path(data_dir, SOURCE_ID, symbol, TIMEFRAME)


def download_etf(data_dir: Path, symbol: str) -> pd.DataFrame:
    """Fetch full daily history for one symbol from Yahoo, merge into its Parquet."""
    df = parse_yahoo_chart(_fetch_chart(symbol))
    path = path_for(data_dir, symbol)
    merged = storage.merge_ohlcv(storage.load_ohlcv(path), df)
    storage.save_ohlcv(merged, path)
    log.info("%s: %d daily rows (%s .. %s)", symbol, len(merged),
             merged["timestamp"].min().date(), merged["timestamp"].max().date())
    return merged


def load_wide_panel(data_dir: Path, symbols: list[str]) -> pd.DataFrame:
    """Close-price panel keeping every symbol's full history, NaN where it had none.

    Unlike `load_panel`, this does not drop rows with gaps. That matters for pairwise
    work such as the correlation screen: aligning on the youngest ticker would silently
    shrink a 10-year question to however long the newest fund has existed — one 2020
    launch truncated a 120-month window to 67 months.
    """
    series: dict[str, pd.Series] = {}
    for sym in symbols:
        df = storage.load_ohlcv(path_for(data_dir, sym))
        if not df.empty:
            series[sym] = df.set_index("timestamp")["close"].sort_index()
    if not series:
        return pd.DataFrame()
    return pd.DataFrame(series).sort_index().ffill()


def load_panel(data_dir: Path, symbols: list[str]) -> pd.DataFrame:
    """Aligned close-price panel: DatetimeIndex, one column per symbol. Starts at
    the first date where every symbol has data; forward-fills interior gaps."""
    series: dict[str, pd.Series] = {}
    for sym in symbols:
        df = storage.load_ohlcv(path_for(data_dir, sym))
        if not df.empty:
            series[sym] = df.set_index("timestamp")["close"].sort_index()
    if not series:
        return pd.DataFrame()
    panel = pd.DataFrame(series).sort_index().ffill().dropna()
    return panel[symbols] if set(symbols) <= set(panel.columns) else panel
