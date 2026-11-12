"""
Tests for the real-data backtest scripts. They never need the dataset itself
(it is not in the repository): they check the cleaning rule, the naive
forecasts and the error measures on small hand-made series.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import pytest

from app import config

sys.path.insert(0, str(config.ROOT / "scripts"))
import uci_backtest as bt  # noqa: E402
import uci_download as dl  # noqa: E402


@pytest.mark.parametrize("code,is_product", [
    ("85123A", True), ("22423", True), ("15056BL", True),
    ("POST", False), ("D", False), ("M", False), ("BANK CHARGES", False),
    ("AMAZONFEE", False), ("C2", False), ("DOT", False), ("TEST001", False),
    ("gift_0001_20", False), ("ADJUST", False), ("", False),
])
def test_product_code_rule(code, is_product):
    assert bool(dl.PRODUCT_CODE.match(code)) is is_product


def _weekly_series(weeks: int = 70) -> dict[date, float]:
    """Mon=100 ... Fri=500, Sat=0 (closed), Sun=700, growing 10 a week."""
    start = date(2010, 1, 4)  # a Monday
    return {start + timedelta(days=i): (0.0 if i % 7 == 5 else (i % 7 + 1) * 100.0 + (i // 7) * 10)
            for i in range(weeks * 7)}


def test_last_week_naive_repeats_the_same_weekday():
    sales = _weekly_series()
    origin = date(2010, 6, 6)  # a Sunday
    f = bt.naive_forecasts(sales, origin, 14)["last_week"]
    assert f[:7] == [sales[origin - timedelta(days=6 - i)] for i in range(7)]
    assert f[7:] == f[:7]
    assert f[5] == 0.0  # Saturday stays closed


def test_last_year_naive_needs_a_year_of_history_and_keeps_weekdays_aligned():
    sales = _weekly_series()
    assert bt.naive_forecasts(sales, date(2010, 6, 6), 14)["last_year"] is None
    origin = date(2011, 3, 6)
    f = bt.naive_forecasts(sales, origin, 14)["last_year"]
    assert f[0] == sales[origin + timedelta(days=1) - timedelta(days=364)]
    assert (origin + timedelta(days=1) - timedelta(days=364)).weekday() == (origin + timedelta(days=1)).weekday()


def test_error_measures():
    total, daily = bt.score([100.0, 300.0], [200.0, 200.0])
    assert total == pytest.approx(0.0)       # the total is right
    assert daily == pytest.approx(50.0)      # each day is off by 100 of 400
    total, daily = bt.score([220.0, 220.0], [200.0, 200.0])
    assert total == pytest.approx(10.0) and daily == pytest.approx(10.0)


def test_model_forecast_uses_the_products_own_projection():
    """A flat closed-on-Saturday series must be projected flat, Saturdays at zero."""
    start = date(2010, 3, 1)  # March to June: seasonal factors 1.00-1.03
    sales = {start + timedelta(days=i): (0.0 if (start + timedelta(days=i)).weekday() == 5 else 1000.0)
             for i in range(150)}
    origin = date(2010, 6, 15)
    f = bt.model_forecast(sales, origin, 14)
    days = [origin + timedelta(days=i) for i in range(1, 15)]
    for d, v in zip(days, f):
        if d.weekday() == 5:
            assert v == 0.0, d
        else:
            assert v == pytest.approx(1000.0, rel=0.06), d
