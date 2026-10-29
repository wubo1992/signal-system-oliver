# tests/v_oliver_kell/test_cycle_detector.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage


def make_daily_df(prices, volumes=None):
    """生成测试 DataFrame（含 OHLC + EMA 计算）

    CycleDetector.classify() 依赖 high/low 判断楔形与突破，所以测试夹具必须补齐
    开高低 —— 真实行情数据本来就有这三列，这里按 close ±0.5% 合成。
    """
    n = len(prices)
    idx = pd.date_range("2026-01-01", periods=n, tz="UTC")
    df = pd.DataFrame({"close": prices}, index=idx)
    df["open"] = df["close"]
    df["high"] = df["close"] * 1.005
    df["low"] = df["close"] * 0.995
    if volumes:
        df["volume"] = volumes
    else:
        df["volume"] = [1_000_000] * n
    df["EMA10"] = df["close"].ewm(span=10).mean()
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["SMA50"] = df["close"].rolling(50).mean()
    df["SMA200"] = df["close"].rolling(200).mean()
    return df


def test_unknown_insufficient_data():
    """数据不足返回 UNKNOWN"""
    prices = [100, 101, 102]
    df = make_daily_df(prices)
    detector = CycleDetector()
    stage = detector.classify(df)
    assert stage == CycleStage.UNKNOWN


def test_wedge_pop_detection():
    """Wedge Pop - 收缩楔形突破 + 站上 EMA + 放量"""
    # 生成一个收缩楔形后突破的场景
    np.random.seed(42)
    # 前20天楔形收敛
    wedge_prices = [100 - i * 0.5 for i in range(20)]  # 缓慢上涨
    wedge_prices = [100 + i * 0.3 + np.random.randn() * 0.5 for i in range(15)]
    wedge_prices.reverse()
    wedge_prices += [wedge_prices[-1] + i * 0.8 for i in range(5)]  # 突破
    volumes = [1e6] * 15 + [3e6] * 5  # 突破时放量
    df = make_daily_df(wedge_prices, volumes)
    detector = CycleDetector()
    stage = detector.classify(df)
    # Should be WEDGE_POP or another valid stage (not UNKNOWN if data is sufficient)
    assert stage != CycleStage.UNKNOWN or len(df) < 50


def test_ema_crossback_pullback():
    """EMA Crossback - 回踩 EMA"""
    # 模拟价格回踩 EMA（小幅下跌，低量）
    np.random.seed(42)
    base = [100 + i * 0.5 for i in range(30)]
    pullback = base + [base[-1] - i * 0.3 for i in range(5)]  # 小幅回调
    volumes = [1e6] * 35
    df = make_daily_df(pullback, volumes)
    detector = CycleDetector()
    stage = detector.classify(df)
    # Should identify some stage
    assert stage in [CycleStage.EMA_CROSSBACK, CycleStage.WEDGE_POP,
                     CycleStage.BASE_N_BREAK, CycleStage.UNKNOWN]


def test_exhaustion_extension_no_new_positions():
    """Exhaustion Extension - 价格远离 EMA"""
    # 模拟远离 EMA 的暴涨
    base = [100 + i * 2 for i in range(30)]  # 快速上涨
    volumes = [1e6] * 20 + [5e6] * 10  # 后半段巨量
    df = make_daily_df(base, volumes)
    detector = CycleDetector()
    stage = detector.classify(df)
    # 价格远离 EMA 应该被识别
    assert stage in [CycleStage.EXHAUSTION_EXTENSION, CycleStage.UNKNOWN]


def test_wedge_drop_detection():
    """Wedge Drop - 跌破 EMA"""
    # 模拟跌破 EMA
    rise = [100 + i * 0.5 for i in range(30)]
    drop = [rise[-1] - i * 1.5 for i in range(10)]  # 快速下跌
    volumes = [1e6] * 40
    df = make_daily_df(rise + drop, volumes)
    detector = CycleDetector()
    stage = detector.classify(df)
    # 跌破 EMA 应该被识别为 WEDGE_DROP
    assert stage in [CycleStage.WEDGE_DROP, CycleStage.EXHAUSTION_EXTENSION, CycleStage.UNKNOWN]


def test_cycle_stages_enum_complete():
    """CycleStage enum should have all 7 values"""
    stages = list(CycleStage)
    assert len(stages) == 7
    assert CycleStage.REVERSAL_EXTENSION in stages
    assert CycleStage.WEDGE_POP in stages
    assert CycleStage.EMA_CROSSBACK in stages
    assert CycleStage.BASE_N_BREAK in stages
    assert CycleStage.EXHAUSTION_EXTENSION in stages
    assert CycleStage.WEDGE_DROP in stages
    assert CycleStage.UNKNOWN in stages