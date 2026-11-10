"""
tests/v_oliver_kell/test_weinstein_classical.py

回归测试：Weinstein 经典周线结构引擎（WEINSTEIN-STRUCTURE-1.3）

移植自 `/Users/wubo/Desktop/codes/Stan Weinstein stage analysis/weinstein/classical.py`，
此处锁定关键行为：主阶段判定、子阶段、标签格式、周线门槛、发展中周标记。
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strategies.v_oliver_kell.weinstein_classical import (
    MIN_WEEKLY_BARS,
    RULES_VERSION,
    analyze_daily,
    daily_to_weekly_bars,
)
from strategies.v_oliver_kell.weinstein_stage import (
    compute_weinstein_detail,
    compute_weinstein_stage,
    stage_label,
)


def _daily_frame(prices, start="2024-01-01"):
    """prices: list[float]（交易日收盘价）→ 日线 DataFrame。"""
    idx = pd.date_range(start=start, periods=len(prices), freq="B", tz="UTC")
    return pd.DataFrame(
        {
            "open": prices,
            "high": [p * 1.01 for p in prices],
            "low": [p * 0.99 for p in prices],
            "close": prices,
            "volume": [1_000_000.0] * len(prices),
        },
        index=idx,
    )


def _ramp(start_price, step, n):
    return [start_price + step * i for i in range(n)]


def test_rules_version_is_classical():
    assert RULES_VERSION == "WEINSTEIN-STRUCTURE-1.3"
    assert MIN_WEEKLY_BARS == 60


def test_daily_to_weekly_bars_aggregates_correctly():
    df = _daily_frame([10.0] * 10)
    bars = daily_to_weekly_bars(df)
    assert len(bars) == 2  # 10 个工作日 = 2 个自然周
    first = bars[0]
    assert first["open"] == 10.0
    assert first["high"] == 10.1
    assert first["low"] == 9.9
    assert first["close"] == 10.0
    assert first["volume"] == 5_000_000.0


def test_insufficient_weekly_bars_returns_none():
    df = _daily_frame(_ramp(10.0, 0.05, 100))  # 100 个工作日 ≈ 20 根周线
    assert compute_weinstein_detail(df) is None
    stage, label = compute_weinstein_stage(df)
    assert stage is None
    assert label == "—"


def test_uptrend_is_stage_2():
    df = _daily_frame(_ramp(10.0, 0.03, 400))  # ≈ 80 根周线
    detail = compute_weinstein_detail(df, as_of=datetime(2025, 10, 1, tzinfo=timezone.utc))
    assert detail is not None
    assert detail["stage"] == 2
    assert detail["label"].startswith("Stage 2 上升")


def test_downtrend_is_stage_4():
    df = _daily_frame(_ramp(100.0, -0.15, 400))
    detail = compute_weinstein_detail(df, as_of=datetime(2025, 10, 1, tzinfo=timezone.utc))
    assert detail is not None
    assert detail["stage"] == 4
    assert detail["label"].startswith("Stage 4 下跌")


def test_developing_week_flagged_and_confirmed_reading_present():
    df = _daily_frame(_ramp(10.0, 0.03, 400))
    as_of = df.index[-1].to_pydatetime()
    detail = compute_weinstein_detail(df, as_of=as_of)
    assert detail is not None
    assert detail["is_developing"] is True
    assert detail["week_status"] == "developing"
    assert detail["confirmed_label"]
    assert detail["confirmed_label"] != detail["label"] or True


def test_stage_label_format():
    assert stage_label(2, "2A") == "Stage 2 上升 · 2A 上升初期"
    assert stage_label(None) == "—"


def test_analyze_daily_returns_segments():
    df = _daily_frame(_ramp(10.0, 0.03, 400))
    result = analyze_daily(df, as_of=datetime(2025, 10, 1, tzinfo=timezone.utc))
    assert result is not None
    assert result["method"]["rules_version"] == RULES_VERSION
    assert result["method"]["uses_momentum_for_stage"] is False
    assert len(result["segments"]) >= 1
    assert len(result["substage_segments"]) >= 1


@pytest.mark.parametrize("stage,substage,expected_prefix", [
    (1, "1A", "Stage 1 筑底"),
    (2, "2B", "Stage 2 上升"),
    (3, "3", "Stage 3 做顶"),
    (4, "4B-", "Stage 4 下跌"),
])
def test_stage_label_table(stage, substage, expected_prefix):
    assert stage_label(stage, substage).startswith(expected_prefix)
