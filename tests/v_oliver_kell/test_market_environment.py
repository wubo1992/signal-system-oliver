# tests/v_oliver_kell/test_market_environment.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.market_environment import MarketEnvironment, MarketState


def make_test_df(prices, ema20_values):
    """生成测试 DataFrame"""
    n = len(prices)
    idx = pd.date_range("2026-01-01", periods=n, tz="UTC")
    df = pd.DataFrame({"close": prices, "EMA20": ema20_values}, index=idx)
    return df


def test_quality_above_ema():
    """原文：Index above 20 EMA → Quality"""
    # 价格持续在 EMA 上方，需要 >= 20 天
    prices = [100 + i for i in range(25)]
    ema20 = [98] * 25  # EMA20 低于价格
    df = make_test_df(prices, ema20)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.QUALITY, f"Expected QUALITY, got {state}"


def test_average_near_ema():
    """原文：Index oscillating near 20 EMA → Average"""
    # 价格在 EMA 附近（1%以内），需要 >= 20 天
    prices = [100 + (i % 3 - 1) * 0.5 for i in range(25)]
    ema20 = [100] * 25
    df = make_test_df(prices, ema20)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.AVERAGE, f"Expected AVERAGE, got {state}"


def test_poor_below_ema():
    """原文：Index below 20 EMA, unable to profit → Poor"""
    # 价格在 EMA 下方振荡（但不是持续下跌），需要 >= 20 天
    prices = []
    for i in range(25):
        # 振荡模式但持续低于 EMA (100)
        if i % 2 == 0:
            prices.append(97 + (i % 5) * 0.1)
        else:
            prices.append(96 + (i % 5) * 0.1)
    ema20 = [100] * 25  # EMA20 高于价格
    df = make_test_df(prices, ema20)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.POOR, f"Expected POOR, got {state}"


def test_hostile_systematic_decline():
    """原文：Systematic decline → Hostile"""
    # 持续下跌（10天中8天以上下跌），需要 >= 20 天
    prices = [100 - i for i in range(25)]  # 24天连续下跌
    ema20 = [100] * 25
    df = make_test_df(prices, ema20)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.HOSTILE, f"Expected HOSTILE, got {state}"


def test_max_position_pct_quality():
    """Quality: ~190% margin"""
    env = MarketEnvironment()
    assert env.max_position_pct(MarketState.QUALITY) == 1.9


def test_max_position_pct_average():
    """Average: 50%"""
    env = MarketEnvironment()
    assert env.max_position_pct(MarketState.AVERAGE) == 0.5


def test_max_position_pct_poor():
    """Poor: 30%"""
    env = MarketEnvironment()
    assert env.max_position_pct(MarketState.POOR) == 0.3


def test_max_position_pct_hostile():
    """Hostile: 0%"""
    env = MarketEnvironment()
    assert env.max_position_pct(MarketState.HOSTILE) == 0.0


def test_insufficient_data():
    """数据不足返回 Hostile"""
    prices = [100, 101]
    ema20 = [98, 99]
    df = make_test_df(prices, ema20)
    env = MarketEnvironment()
    state = env.classify(df)
    assert state == MarketState.HOSTILE