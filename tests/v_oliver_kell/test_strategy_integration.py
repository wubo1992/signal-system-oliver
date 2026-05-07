"""
集成测试：用历史数据验证策略逻辑
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell import OliverKellStrategy
from events import EventQueue


def make_realistic_df(days: int, start_price: float = 100.0):
    """生成逼真的价格数据（带 EMA 计算）"""
    idx = pd.date_range("2025-01-01", periods=days, tz="UTC")
    np.random.seed(42)

    # 模拟牛市趋势
    trend = np.linspace(0, 20, days)  # 缓慢上涨趋势
    noise = np.random.randn(days) * 2  # 噪音
    prices = start_price + trend + noise

    df = pd.DataFrame({"close": prices}, index=idx)
    df["volume"] = [1_000_000] * days
    df["open"] = df["close"] * (1 + np.random.randn(days) * 0.005)
    df["high"] = df["close"] * (1 + np.abs(np.random.randn(days)) * 0.01)
    df["low"] = df["close"] * (1 - np.abs(np.random.randn(days)) * 0.01)

    # EMA
    df["EMA10"] = df["close"].ewm(span=10).mean()
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["SMA50"] = df["close"].rolling(50).mean()
    df["SMA200"] = df["close"].rolling(200).mean()

    return df


def test_strategy_initialization():
    """策略可以正常初始化"""
    config = {
        "wedge_lookback": 20,
        "base_lookback": 20,
        "index_symbol": "QQQ",
        "require_wedge_pop_first": True,
    }
    market_data = {}
    strategy = OliverKellStrategy(config, market_data, live_mode=False)
    assert strategy.strategy_id == "v_oliver_kell"
    assert strategy.strategy_name == "Oliver Kell Cycle of Price Action"


def test_strategy_run_date_no_crash():
    """run_date 运行不崩溃"""
    config = {
        "wedge_lookback": 20,
        "base_lookback": 20,
        "index_symbol": "QQQ",
        "require_wedge_pop_first": True,
    }

    qqq_df = make_realistic_df(100, 450)
    aapl_df = make_realistic_df(100, 180)

    market_data = {
        "QQQ": qqq_df,
        "AAPL": aapl_df,
    }

    strategy = OliverKellStrategy(config, market_data, live_mode=False)
    queue = EventQueue()

    date = pd.Timestamp("2025-04-10", tz="UTC").to_pydatetime()
    signals = strategy.run_date(date, queue)

    # 不崩溃即可
    assert isinstance(signals, list)


def test_market_environment_classification():
    """市场环境分类"""
    config = {"index_symbol": "QQQ"}
    market_data = {}
    strategy = OliverKellStrategy(config, market_data)

    # 模拟 QQQ 在 20 EMA 上方
    qqq_df = make_realistic_df(50, 450)
    market_data = {"QQQ": qqq_df}

    from strategies.v_oliver_kell.market_environment import MarketState
    env = strategy.market_env
    state = env.classify(qqq_df)
    assert state in [MarketState.QUALITY, MarketState.AVERAGE, MarketState.POOR, MarketState.HOSTILE]