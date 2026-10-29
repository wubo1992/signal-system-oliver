"""
tests/signals/test_generator_columns.py

回归测试：signals/generator.py 输出包含 RS (10D/20D/10W) + 量比 + O'Neil RS评级/RS倍数 列
"""
import csv
from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from events import SignalEvent
from signals.generator import (
    _CSV_HEADERS,
    _event_to_record,
    _append_to_csv,
    process_signals,
    _print_table,
)
from events import EventQueue, EventType


def test_csv_headers_include_rs_and_vol_ratio():
    """_CSV_HEADERS 必须包含 RS (10D/20D/10W)、量比、RS评级、RS倍数 列。"""
    assert "RS (10D)" in _CSV_HEADERS
    assert "RS (20D)" in _CSV_HEADERS
    assert "RS (10W)" in _CSV_HEADERS
    assert "量比" in _CSV_HEADERS
    assert "RS评级" in _CSV_HEADERS
    assert "RS倍数" in _CSV_HEADERS
    # 总列数 = 13
    assert len(_CSV_HEADERS) == 13


def test_event_to_record_includes_rs_volume_ratio():
    """_event_to_record 必须从 event.data 读 rs_value_10d/20d/10w + volume_ratio。"""
    event = SignalEvent(
        type=EventType.SIGNAL,
        symbol="AAPL",
        timestamp=datetime(2026, 8, 6, tzinfo=timezone.utc),
        data={
            "direction": "buy",
            "strength": 5,
            "reason": "[Wedge Pop] | [RS] 105.20 | [Vol] 1.8x | [Stage] wedge_pop",
            "stop_loss": 100.5,
            "shares": 0.0,
            "rs_value_10d": 1.0250,
            "rs_value": 1.0520,
            "rs_value_10w": 0.9800,
            "volume_ratio": 1.8,
            "rs_rating": 88,
            "rs_ratio": 1.4231,
        },
    )

    record = _event_to_record(event)

    assert "RS (10D)" in record
    assert "RS (20D)" in record
    assert "RS (10W)" in record
    assert "量比" in record
    assert "RS评级" in record
    assert "RS倍数" in record
    assert record["RS (10D)"] == "1.0250"
    assert record["RS (20D)"] == "1.0520"
    assert record["RS (10W)"] == "0.9800"
    assert record["量比"] == "1.8x"
    assert record["RS评级"] == "88"
    assert record["RS倍数"] == "1.4231"


def test_event_to_record_handles_missing_rs_vol():
    """数据缺失时 RS/量比应为 '—'。"""
    event = SignalEvent(
        type=EventType.SIGNAL,
        symbol="AAPL",
        timestamp=datetime(2026, 8, 6, tzinfo=timezone.utc),
        data={
            "direction": "buy",
            "strength": 4,
            "reason": "[EMA Crossback] Entry",
            "stop_loss": 90.0,
            "shares": 0.0,
            # 没有 rs_value / volume_ratio
        },
    )

    record = _event_to_record(event)

    assert record["RS (10D)"] == "—"
    assert record["RS (20D)"] == "—"
    assert record["RS (10W)"] == "—"
    assert record["量比"] == "—"
    assert record["RS评级"] == "—"
    assert record["RS倍数"] == "—"


def test_append_to_csv_writes_rs_vol_columns(tmp_path, monkeypatch):
    """_append_to_csv 应该写入 13 列 schema，包括 RS (10D/20D/10W) + 量比 + RS评级 + RS倍数。"""
    # 创建策略目录
    strategy_id = "test_strategy_csv"
    strategy_dir = tmp_path / strategy_id
    strategy_dir.mkdir(parents=True, exist_ok=True)
    signals_csv = strategy_dir / "signals.csv"

    # 修正 OUTPUT_DIR (monkeypatch)
    import signals.generator as gen_mod

    monkeypatch.setattr(gen_mod, "OUTPUT_DIR", tmp_path)

    event = SignalEvent(
        type=EventType.SIGNAL,
        symbol="NVDA",
        timestamp=datetime(2026, 8, 6, tzinfo=timezone.utc),
        data={
            "direction": "buy",
            "strength": 5,
            "reason": "[Wedge Pop] Best entry | [RS] 110.50 | [Vol] 2.3x | [Stage] wedge_pop",
            "stop_loss": 120.0,
            "shares": 0.0,
            "rs_value_10d": 1.1050,
            "rs_value": 1.1050,
            "rs_value_10w": 1.1050,
            "volume_ratio": 2.3,
            "rs_rating": 91,
            "rs_ratio": 2.0075,
        },
    )

    record = _event_to_record(event)
    _append_to_csv([record], strategy_id=strategy_id)

    # 重新读取
    with open(signals_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["股票"] == "NVDA"
    assert rows[0]["RS (20D)"] == "1.1050"
    assert rows[0]["量比"] == "2.3x"
    assert rows[0]["RS评级"] == "91"
    assert rows[0]["RS倍数"] == "2.0075"


def test_append_to_csv_migrates_old_schema(tmp_path, monkeypatch):
    """旧 7 列 CSV 应该自动迁移到 13 列 schema。"""
    strategy_id = "test_strategy_migrate"
    strategy_dir = tmp_path / strategy_id
    strategy_dir.mkdir(parents=True, exist_ok=True)
    signals_csv = strategy_dir / "signals.csv"

    # 写入旧 7 列 schema
    old_headers = ["日期", "股票", "信号", "强度(1-5)", "触发原因", "参考止损", "持仓股数"]
    with open(signals_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(old_headers)
        writer.writerow(["2026-08-05", "AAPL", "买入", 5, "[Wedge Pop] Best entry", "$100.00", "—"])

    import signals.generator as gen_mod
    monkeypatch.setattr(gen_mod, "OUTPUT_DIR", tmp_path)

    # 触发迁移
    event = SignalEvent(
        type=EventType.SIGNAL,
        symbol="MSFT",
        timestamp=datetime(2026, 8, 6, tzinfo=timezone.utc),
        data={
            "direction": "buy",
            "strength": 4,
            "reason": "[EMA Crossback] Entry | [RS] 99.10 | [Vol] 1.2x",
            "stop_loss": 95.0,
            "shares": 0.0,
            "rs_value_10d": 0.9910,
            "rs_value": 0.9910,
            "rs_value_10w": 0.9910,
            "volume_ratio": 1.2,
            "rs_rating": 72,
            "rs_ratio": 0.8810,
        },
    )
    record = _event_to_record(event)
    _append_to_csv([record], strategy_id=strategy_id)

    # 验证 header 是 13 列
    with open(signals_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == _CSV_HEADERS
    assert len(rows) == 2

    # 旧行迁移后 RS/量比/RS评级/RS倍数 是 '—'
    assert rows[0]["RS (10D)"] == "—"
    assert rows[0]["RS (20D)"] == "—"
    assert rows[0]["RS (10W)"] == "—"
    assert rows[0]["量比"] == "—"
    assert rows[0]["RS评级"] == "—"
    assert rows[0]["RS倍数"] == "—"
    # 新行有真实值
    assert rows[1]["RS (20D)"] == "0.9910"
    assert rows[1]["量比"] == "1.2x"
    assert rows[1]["RS评级"] == "72"
    assert rows[1]["RS倍数"] == "0.8810"

    # 备份文件存在
    backups = list(strategy_dir.glob("signals.csv.bak.*"))
    assert len(backups) == 1


def test_append_to_csv_migrates_11col_to_13col(tmp_path, monkeypatch):
    """旧的 11 列 CSV（已有 RS 三列但无 RS评级/RS倍数）应该迁移到 13 列。"""
    strategy_id = "test_strategy_migrate_11"
    strategy_dir = tmp_path / strategy_id
    strategy_dir.mkdir(parents=True, exist_ok=True)
    signals_csv = strategy_dir / "signals.csv"

    old_headers = [
        "日期", "股票", "信号", "强度(1-5)", "触发原因", "参考止损", "持仓股数",
        "RS (10D)", "RS (20D)", "RS (10W)", "量比",
    ]
    with open(signals_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(old_headers)
        writer.writerow([
            "2026-08-05", "AAPL", "买入", 5, "[Wedge Pop] Best entry", "$100.00", "—",
            "1.0200", "1.0500", "0.9800", "1.8x",
        ])

    import signals.generator as gen_mod
    monkeypatch.setattr(gen_mod, "OUTPUT_DIR", tmp_path)

    _append_to_csv([], strategy_id=strategy_id)  # 空 records 也会触发迁移检查

    with open(signals_csv, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert reader.fieldnames == _CSV_HEADERS
    assert len(rows) == 1
    # 旧行原有 RS 三列保留，新列填 '—'
    assert rows[0]["RS (10D)"] == "1.0200"
    assert rows[0]["RS (20D)"] == "1.0500"
    assert rows[0]["RS (10W)"] == "0.9800"
    assert rows[0]["量比"] == "1.8x"
    assert rows[0]["RS评级"] == "—"
    assert rows[0]["RS倍数"] == "—"

    backups = list(strategy_dir.glob("signals.csv.bak.*"))
    assert len(backups) == 1
