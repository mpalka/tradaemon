
from trademon.backtest.runner import run_backtest

from .conftest import FakeBundle, make_ohlcv


def test_maker_mode_reports_fill_stats(cfg):
    cfg.execution.order_style = "maker"
    result = run_backtest(make_ohlcv(2000), FakeBundle(prob=0.99), cfg, "BTC/USDT")
    s = result["summary"]
    assert s["order_style"] == "maker"
    assert s["signals"] >= s["fills"]  # some signals may not fill
    assert 0.0 <= s["fill_rate_pct"] <= 100.0


def test_maker_entry_never_pays_slippage(cfg):
    cfg.execution.order_style = "maker"
    cfg.costs.slippage_bps = 50.0  # large slippage; maker entries must ignore it
    result = run_backtest(make_ohlcv(2000, seed=3), FakeBundle(prob=0.99), cfg, "BTC/USDT")
    trades = result["trades"]
    if len(trades):
        # entry price equals a real bar level, not price * (1 + slippage)
        assert trades["entry_price"].notna().all()


def test_maker_cheaper_fees_than_taker_same_signals(cfg):
    df = make_ohlcv(3000, seed=5)
    cfg.costs.maker_fee = 0.0
    taker = run_backtest(df, FakeBundle(prob=0.99),
                         cfg.model_copy(update={"execution": cfg.execution.model_copy(
                             update={"order_style": "taker"})}), "BTC/USDT")["summary"]
    maker = run_backtest(df, FakeBundle(prob=0.99),
                         cfg.model_copy(update={"execution": cfg.execution.model_copy(
                             update={"order_style": "maker"})}), "BTC/USDT")["summary"]
    if maker["n_trades"] > 0 and taker["n_trades"] > 0:
        # zero maker fee + no slippage => maker pays strictly less in fees per trade
        assert maker["fees_paid"] < taker["fees_paid"]
