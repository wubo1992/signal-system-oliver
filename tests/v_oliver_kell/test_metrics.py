"""
tests/v_oliver_kell/test_metrics.py

回归测试：compute_volume_ratio + compute_rs_line
"""
import pandas as pd
import numpy as np
from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from strategies.v_oliver_kell.cycle_detector import CycleDetector


def make_daily_df(prices, volumes=None, n=None):
    """生成测试 DataFrame。"""
    if n is None:
        n = len(prices)
    idx = pd.date_range("2026-01-01", periods=n, tz="UTC")
    df = pd.DataFrame({"close": list(prices)}, index=idx)
    if volumes is not None:
        df["volume"] = list(volumes)
    else:
        df["volume"] = [1_000_000] * n
    df["EMA10"] = df["close"].ewm(span=10).mean()
    df["EMA20"] = df["close"].ewm(span=20).mean()
    return df


def test_compute_volume_ratio_basic():
    """基本场景：今日成交量是 20 日均量的 N 倍，应返回 N。"""
    n = 21
    # 历史上每天 1,000,000，今天 2,000,000 → ratio = 2.0
    volumes = [1_000_000] * (n - 1) + [2_000_000]
    prices = [100.0] * n
    df = make_daily_df(prices, volumes, n=n)
    detector = CycleDetector()
    ratio = detector.compute_volume_ratio(df, lookback=20)
    assert ratio is not None
    assert abs(ratio - 2.0) < 0.001


def test_compute_volume_ratio_zero_avg():
    """均量为 0 时应返回 None（避免除零）。"""
    n = 30
    volumes = [0] * (n - 1) + [1_000]  # 均量为 0，今日非零
    prices = [100.0] * n
    df = make_daily_df(prices, volumes, n=n)
    detector = CycleDetector()
    ratio = detector.compute_volume_ratio(df, lookback=20)
    assert ratio is None


def test_compute_volume_ratio_short_data():
    """数据不足时应返回 None。"""
    n = 10  # lookback + 1 = 21，少于则 None
    volumes = [1_000_000] * n
    prices = [100.0] * n
    df = make_daily_df(prices, volumes, n=n)
    detector = CycleDetector()
    ratio = detector.compute_volume_ratio(df, lookback=20)
    assert ratio is None


def test_compute_volume_ratio_custom_lookback():
    """自定义 lookback=5：今日 / 前 5 日均量。"""
    n = 7
    # 5 日均量：(1+1+1+1+1)/5=1，今日=1.5 → 1.5
    volumes = [1.0] * (n - 1) + [1.5]
    prices = [100.0] * n
    df = make_daily_df(prices, volumes, n=n)
    detector = CycleDetector()
    ratio = detector.compute_volume_ratio(df, lookback=5)
    assert ratio is not None
    assert abs(ratio - 1.5) < 0.001


def test_compute_rs_line_value_format():
    """compute_rs_line 返回 Series 且最后一项为 float（在合理范围内）。"""
    n = 25
    np.random.seed(42)
    prices = 100 + np.random.randn(n)
    df = make_daily_df(prices, n=n)
    benchmark = make_daily_df([500.0] * n, [1e6] * n, n=n)

    detector = CycleDetector()
    rs = detector.compute_rs_line(df, benchmark)

    # 类型检查
    assert isinstance(rs, pd.Series)
    assert not rs.empty

    # 最后一项是 float，且在合理范围（避免极端值如 0 / inf / nan）
    last = float(rs.iloc[-1])
    assert isinstance(last, float)
    assert last > 0  # 不为负或 0
    assert last < 1_000_000  # 不为天文数字
    assert not (last != last)  # 不是 NaN
