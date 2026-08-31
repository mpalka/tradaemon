import pytest

from tradaemon.config import CostsConfig
from tradaemon.execution.fills import (
    buy_fill,
    check_bracket_exit,
    limit_buy_fills,
    maker_buy_fill,
    maker_sell_fill,
    sell_fill,
)

COSTS = CostsConfig(taker_fee=0.001, maker_fee=0.0005, slippage_bps=10.0)  # 0.1% slippage


def test_buy_fill_applies_adverse_slippage_and_fee():
    fill = buy_fill(100.0, qty=2.0, costs=COSTS)
    assert fill.price == pytest.approx(100.1)   # pays more
    assert fill.notional == pytest.approx(200.2)
    assert fill.fee == pytest.approx(0.2002)


def test_sell_fill_applies_adverse_slippage_and_fee():
    fill = sell_fill(100.0, qty=2.0, costs=COSTS)
    assert fill.price == pytest.approx(99.9)    # receives less
    assert fill.fee == pytest.approx(0.1998)


def test_round_trip_at_same_price_loses_costs():
    b = buy_fill(100.0, 1.0, COSTS)
    s = sell_fill(100.0, 1.0, COSTS)
    pnl = (s.notional - s.fee) - (b.notional + b.fee)
    assert pnl < 0  # fees + slippage must make a flat round-trip negative


def test_maker_fills_have_no_slippage_and_maker_fee():
    b = maker_buy_fill(100.0, qty=2.0, costs=COSTS)
    assert b.price == pytest.approx(100.0)      # no slippage, fills at limit
    assert b.fee == pytest.approx(200.0 * 0.0005)
    s = maker_sell_fill(100.0, qty=2.0, costs=COSTS)
    assert s.price == pytest.approx(100.0)
    assert s.fee == pytest.approx(200.0 * 0.0005)


def test_maker_cheaper_than_taker_round_trip():
    taker = (sell_fill(100.0, 1.0, COSTS).notional - sell_fill(100.0, 1.0, COSTS).fee) - (
        buy_fill(100.0, 1.0, COSTS).notional + buy_fill(100.0, 1.0, COSTS).fee
    )
    maker = (
        maker_sell_fill(100.0, 1.0, COSTS).notional - maker_sell_fill(100.0, 1.0, COSTS).fee
    ) - (maker_buy_fill(100.0, 1.0, COSTS).notional + maker_buy_fill(100.0, 1.0, COSTS).fee)
    assert maker > taker  # less cost lost on a flat round trip


def test_limit_buy_fills_only_when_price_reaches_it():
    assert limit_buy_fills(bar_low=99.0, limit_price=100.0) is True   # dipped to limit
    assert limit_buy_fills(bar_low=100.5, limit_price=100.0) is False  # never reached


def test_bracket_exit_priorities():
    assert check_bracket_exit(103.0, 100.5, tp=102.0, sl=99.0) == "tp"
    assert check_bracket_exit(100.5, 98.0, tp=102.0, sl=99.0) == "sl"
    assert check_bracket_exit(100.5, 100.0, tp=102.0, sl=99.0) is None
    # both touched in one bar -> conservative stop-loss
    assert check_bracket_exit(103.0, 98.0, tp=102.0, sl=99.0) == "sl"
