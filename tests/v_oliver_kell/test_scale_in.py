# tests/v_oliver_kell/test_scale_in.py
import pytest
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.scale_in import ScaleInManager, BatchState, PositionBatch


def test_batch1_initial_entry():
    """Batch 1: 初始 15% 仓位"""
    manager = ScaleInManager()
    # 假设没有持仓
    assert manager.get_batch_state("AAPL") == BatchState.NONE

    # Wedge Pop 入场
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)
    state = manager.get_batch_state("AAPL")
    assert state == BatchState.BATCH1_OPEN
    assert manager.get_position_pct("AAPL") == 15.0


def test_batch2_add_on():
    """Batch 2: 次日确认后加仓至 30%"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)

    # 第二天价格确认上涨
    manager.update_highest_price("AAPL", 105.0)  # Batch 1 已盈利
    manager.on_follow_through("AAPL", follow_through_low=103.0)
    state = manager.get_batch_state("AAPL")
    assert state == BatchState.BATCH2_OPEN
    assert manager.get_position_pct("AAPL") == 30.0


def test_stop_raised_after_batch2():
    """Batch 2 后止损上移至 follow-through day low"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)
    batch1_stop = manager.get_stop("AAPL")

    manager.update_highest_price("AAPL", 105.0)
    manager.on_follow_through("AAPL", follow_through_low=103.0)
    batch2_stop = manager.get_stop("AAPL")

    # Batch 2 止损应该是 follow-through low
    assert batch2_stop == 103.0


def test_batch2_not_profitable():
    """Batch 1 未盈利时不能加 Batch 2"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)

    # 没有更新 highest_price，所以 Batch 1 未盈利
    result = manager.on_follow_through("AAPL", follow_through_low=99.0)
    assert result is None  # 不允许加仓


def test_should_add_batch2():
    """should_add_batch2 逻辑"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)

    # 未盈利
    assert manager.should_add_batch2("AAPL") is False

    # 盈利
    manager.update_highest_price("AAPL", 105.0)
    assert manager.should_add_batch2("AAPL") is True

    # Batch 2 已完成
    manager.on_follow_through("AAPL", follow_through_low=103.0)
    assert manager.should_add_batch2("AAPL") is False


def test_position_batch_total_shares():
    """PositionBatch.total_shares()"""
    batch = PositionBatch(
        symbol="AAPL",
        batch1_entry_price=100.0,
        batch1_entry_date=datetime.now(timezone.utc),
        batch1_stop=98.0,
        batch1_shares=15,
        batch2_entry_price=105.0,
        batch2_entry_date=datetime.now(timezone.utc),
        batch2_shares=15,
        highest_price=110.0,
    )
    assert batch.total_shares() == 30


def test_position_batch_avg_cost():
    """PositionBatch.avg_cost()"""
    batch = PositionBatch(
        symbol="AAPL",
        batch1_entry_price=100.0,
        batch1_entry_date=datetime.now(timezone.utc),
        batch1_stop=98.0,
        batch1_shares=10,
        batch2_entry_price=110.0,
        batch2_entry_date=datetime.now(timezone.utc),
        batch2_shares=10,
        highest_price=120.0,
    )
    # (100*10 + 110*10) / 20 = 105
    assert batch.avg_cost() == 105.0


def test_scale_in_manager_to_dict():
    """序列化 to_dict"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)
    d = manager.to_dict("AAPL")
    assert d is not None
    assert d["symbol"] == "AAPL"
    assert d["batch_1_entry_price"] == 100.0
    assert d["batch_1_stop"] == 98.0


def test_scale_in_manager_from_dict():
    """反序列化 from_dict"""
    data = {
        "symbol": "AAPL",
        "batch_1_entry_price": 100.0,
        "batch_1_entry_date": "2026-05-01T00:00:00+00:00",
        "batch_1_shares": 10,
        "batch_1_stop": 98.0,
        "batch_2_entry_price": 0.0,
        "batch_2_entry_date": None,
        "batch_2_shares": 0,
        "batch_2_stop": 0.0,
        "follow_through_low": 0.0,
        "highest_price": 100.0,
        "current_stage": "wedge_pop",
    }
    batch = ScaleInManager.from_dict(data)
    assert batch.symbol == "AAPL"
    assert batch.batch1_entry_price == 100.0
    assert batch.batch1_shares == 10