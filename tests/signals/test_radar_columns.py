"""
tests/signals/test_radar_columns.py

回归测试：oliver_kell_radar_report 8 模块表头含 RS 10D / RS 20D / RS 10W / Vol Ratio
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from signals.oliver_kell_radar_report import (
    _record_to_dict,
    _format_rs,
    _format_vol,
    categorize_signals,
    _build_radar_report,
)
from events import SignalEvent, EventType


def test_record_to_dict_includes_rs_volume():
    """_record_to_dict 必须从 SignalEvent.data 取 rs_value_10d/20d/10w + volume_ratio。"""
    event = SignalEvent(
        type=EventType.SIGNAL,
        symbol="AAPL",
        timestamp=datetime(2026, 8, 6, tzinfo=timezone.utc),
        data={
            "direction": "buy",
            "strength": 5,
            "reason": "[Wedge Pop] Best entry",
            "rs_value_10d": 1.0250,
            "rs_value": 1.0520,
            "rs_value_10w": 0.9800,
            "volume_ratio": 1.8,
        },
    )
    rec = _record_to_dict(event)
    assert rec["RS (10D)"] == 1.0250
    assert rec["RS (20D)"] == 1.0520
    assert rec["RS (10W)"] == 0.9800
    assert rec["量比"] == 1.8


def test_format_rs_handles_none_and_numbers():
    """_format_rs 输出 4 位小数（倍数形式）。"""
    assert _format_rs(None) == "—"
    assert _format_rs(1.05234) == "1.0523"
    assert _format_rs(1.0) == "1.0000"
    assert _format_rs(0) == "0.0000"


def test_format_vol_handles_none_and_numbers():
    assert _format_vol(None) == "—"
    assert _format_vol(1.85) == "1.9x"
    assert _format_vol(0) == "0.0x"


def test_build_radar_report_includes_rs_and_volume_columns():
    """_build_radar_report 输出的 Markdown 含 RS 10D / RS 20D / RS 10W / Vol Ratio 表头。"""
    # 构造多类信号
    records = [
        # LONG_ENTRIES
        {
            "股票": "NVDA",
            "信号": "买入",
            "强度(1-5)": 5,
            "强度星级": "★★★★★",
            "触发原因": "[Wedge Pop] Best entry | [RS] 110.50 | [Vol] 2.3x | [Stage] wedge_pop",
            "cycle_stage": "wedge_pop",
            "RS (10D)": 1.1050,
            "RS (20D)": 1.1050,
            "RS (10W)": 1.1050,
            "量比": 2.3,
            "参考止损": "$120.00",
            "日期": "2026-08-06",
        },
        {
            "股票": "AMD",
            "信号": "买入",
            "强度(1-5)": 4,
            "强度星级": "★★★★☆",
            "触发原因": "[EMA Crossback] Entry | [RS] 95.20 | [Vol] 1.5x | [Stage] ema_crossback",
            "cycle_stage": "ema_crossback",
            "RS (10D)": 0.9520,
            "RS (20D)": 0.9520,
            "RS (10W)": 0.9520,
            "量比": 1.5,
            "参考止损": "$80.00",
            "日期": "2026-08-06",
        },
        # SHORT_ENTRIES
        {
            "股票": "META",
            "信号": "做空",
            "强度(1-5)": 4,
            "强度星级": "★★★★☆",
            "触发原因": "[Wedge Drop Short] Entry | [RS] 88.00 | [Vol] 1.7x | [Stage] wedge_drop_short",
            "cycle_stage": "wedge_drop_short",
            "RS (10D)": 0.8800,
            "RS (20D)": 0.8800,
            "RS (10W)": 0.8800,
            "量比": 1.7,
            "参考止损": "$200.00",
            "日期": "2026-08-06",
        },
        # WATCHLIST（base_tightening）
        {
            "股票": "PLTR",
            "信号": "观望",
            "强度(1-5)": 2,
            "强度星级": "★★☆☆☆",
            "触发原因": "[Base Tightening] Price above EMA20 | [RS] 90.10 | [Vol] 1.2x | [Stage] base_tightening",
            "cycle_stage": "base_tightening",
            "RS (10D)": 0.9010,
            "RS (20D)": 0.9010,
            "RS (10W)": 0.9010,
            "量比": 1.2,
            "参考止损": "$30.00",
            "日期": "2026-08-06",
        },
    ]
    modules = categorize_signals(records)
    md = _build_radar_report("2026-08-06", "Test Strategy", modules)

    # 表头检查
    assert "RS 10D" in md
    assert "RS 20D" in md
    assert "RS 10W" in md
    assert "Vol Ratio" in md
    # 长信号区
    assert "| Ticker | Strength | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Action | Stop Loss | Context |" in md
    # 短信号区
    assert "| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Signal | Action | Stop Loss | Context |" in md
    # Watchlist
    assert "| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Stage | Context |" in md


def test_build_radar_report_handles_missing_rs_volume():
    """没有 RS/Vol 时列内显示 '—'（不抛错）。"""
    records = [
        {
            "股票": "TEST",
            "信号": "买入",
            "强度(1-5)": 5,
            "强度星级": "★★★★★",
            "触发原因": "[Wedge Pop] Best entry",
            "cycle_stage": "wedge_pop",
            "RS (10D)": None,
            "RS (20D)": None,
            "RS (10W)": None,
            "量比": None,
            "参考止损": "$100.00",
            "日期": "2026-08-06",
        },
    ]
    modules = categorize_signals(records)
    md = _build_radar_report("2026-08-06", "Test", modules)
    # 行里应该出现 — 因为没有值
    assert "— | — | — | — | Buy" in md or "| — | — | — | — | Buy" in md
