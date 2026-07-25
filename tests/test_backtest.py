import pytest

from trademon.backtest.runner import render_report, run_backtest

from .conftest import FakeBundle, make_ohlcv


def test_backtest_executes_trades_and_accounts_for_costs(cfg):
    df = make_ohlcv(2000)
    result = run_backtest(df, FakeBundle(prob=0.99), cfg, "BTC/USDT")
    s = result["summary"]

    assert s["n_trades"] > 0
    assert s["fees_paid"] > 0
    # accounting identity: gross pnl minus fees equals net pnl
    assert s["gross_pnl"] - s["fees_paid"] == pytest.approx(s["net_pnl"])
    # every closed trade's pnl matches its fills
    trades = result["trades"]
    recomputed = trades["qty"] * (trades["exit_price"] - trades["entry_price"])
    slippage_free = recomputed - trades["pnl"] - trades["fees"]
    assert (slippage_free.abs() < 1e-6).all()


def test_backtest_no_signals_no_trades(cfg):
    df = make_ohlcv(600)
    result = run_backtest(df, FakeBundle(prob=0.0), cfg, "BTC/USDT")
    assert result["summary"]["n_trades"] == 0
    assert result["summary"]["total_return_pct"] == pytest.approx(0.0)


def test_report_contains_verdict(cfg):
    df = make_ohlcv(800)
    result = run_backtest(df, FakeBundle(prob=0.99), cfg, "BTC/USDT")
    report = render_report([result], cfg)
    assert "VERDICT" in report
    assert "BTC/USDT" in report
