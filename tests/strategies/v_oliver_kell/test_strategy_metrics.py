"""
tests/strategies/v_oliver_kell/test_strategy_metrics.py

回归测试：strategy 产出的 SignalEvent.data 必须包含 rs_value + volume_ratio
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

import pandas as pd
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from strategies.v_oliver_kell import OliverKellStrategy
from events import EventQueue


def make_wedge_pop_df(days=30, base_price=100.0):
    """构造一个触发 Wedge Pop 的价格序列（楔形+突破）。"""
    np.random.seed(42)
    idx = pd.date_range("2026-01-01", periods=days, tz="UTC")

    # 前 20 天楔形（向下倾斜），后 10 天突破
    prices = []
    for i in range(20):
        prices.append(base_price - i * 0.3 + np.random.randn() * 0.5)
    for i in range(days - 20):
        prices.append(prices[-1] + 0.8 + np.random.randn() * 0.3)

    df = pd.DataFrame({"close": prices}, index=idx)
    df["open"] = df["close"] * (1 + np.random.randn(days) * 0.005)
    df["high"] = df["close"] * (1 + np.abs(np.random.randn(days)) * 0.01)
    df["low"] = df["close"] * (1 - np.abs(np.random.randn(days)) * 0.01)
    df["volume"] = [1_000_000] * (days - 5) + [3_000_000] * 5  # 突破日放量
    df["EMA10"] = df["close"].ewm(span=10).mean()
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["SMA50"] = df["close"].rolling(50).mean()
    df["SMA200"] = df["close"].rolling(200).mean()
    return df


def make_spy_df(days=30, base_price=500.0):
    """构造 SPY 行情数据（用作 RS 基准）。"""
    idx = pd.date_range("2026-01-01", periods=days, tz="UTC")
    prices = [base_price + i * 0.3 + np.random.randn() * 1.0 for i in range(days)]
    df = pd.DataFrame({"close": prices}, index=idx)
    df["volume"] = [50_000_000] * days
    return df


def test_compute_signal_metrics_returns_floats():
    """strategy._compute_signal_metrics 应该返回 4-tuple（RS 10D/20D/10W + 量比），任一项可为 None。"""
    cfg = {
        "wedge_lookback": 20,
        "base_lookback": 20,
        "index_symbol": "QQQ",
        "rs_benchmark": "SPY",
        "volume_ratio_window": 20,
        "require_wedge_pop_first": True,
    }
    df_stock = make_wedge_pop_df()
    df_spy = make_spy_df()

    market_data = {
        "AAPL": df_stock,
        "SPY": df_spy,
    }

    strategy = OliverKellStrategy(cfg, market_data, live_mode=False)

    rs_10d, rs_20d, rs_10w, vol_ratio = strategy._compute_signal_metrics(df_stock)
    # 每项都应为 float 或 None（数据量不足 / 基准缺失时降级为 None）
    for v in (rs_10d, rs_20d, rs_10w, vol_ratio):
        assert v is None or isinstance(v, float)


def test_handle_ema_crossback_emits_rs_and_volume_ratio():
    """_handle_ema_crossback 产出的 SignalEvent.data 必须含 rs_value + volume_ratio。"""
    cfg = {
        "wedge_lookback": 20,
        "base_lookback": 20,
        "index_symbol": "QQQ",
        "rs_benchmark": "SPY",
        "volume_ratio_window": 20,
        "require_wedge_pop_first": True,
    }
    df_stock = make_wedge_pop_df()
    df_spy = make_spy_df()

    market_data = {
        "AAPL": df_stock,
        "SPY": df_spy,
    }
    strategy = OliverKellStrategy(cfg, market_data, live_mode=False)

    last_date = df_stock.index[-1].to_pydatetime().replace(tzinfo=None)
    last_date = last_date.replace(tzinfo=timezone.utc)

    # 用 mocked close/EMA
    close = float(df_stock["close"].iloc[-1])
    ema10 = float(df_stock["EMA10"].iloc[-1])
    ema20 = float(df_stock["EMA20"].iloc[-1])

    from strategies.v_oliver_kell.cycle_detector import CycleStage

    # 调用 handler（mock stage）
    event = strategy._handle_ema_crossback(
        symbol="AAPL",
        df=df_stock,
        date=last_date,
        close=close,
        ema10=ema10,
        ema20=ema20,
        stage=CycleStage.EMA_CROSSBACK,
        qqq_df=None,
    )

    # event 应该存在
    assert event is not None

    # data 字段包含 rs_value + volume_ratio
    assert "rs_value" in event.data
    assert "volume_ratio" in event.data

    # reason 文本含 [RS] 与 [Vol] token（即使数值为 None 不显示，也至少不崩）
    reason = event.data["reason"]
    assert "[EMA Crossback]" in reason

    # 如果有值，reason 应该包含相应 token
    if event.data["rs_value"] is not None:
        assert "[RS]" in reason
    if event.data["volume_ratio"] is not None:
        assert "[Vol]" in reason
