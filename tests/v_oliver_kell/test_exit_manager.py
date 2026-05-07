# tests/v_oliver_kell/test_exit_manager.py
import pytest
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.exit_manager import ExitManager, ExitReason, ExitDecision


def test_fixed_stop_loss():
    """原文：Stop: Below breakout day closing low"""
    manager = ExitManager()
    # 亏损 2% 触发止损
    entry = 100.0
    stop = manager.calculate_stop(entry, scenario="wedge_pop")
    assert stop == 98.0  # 2% below entry


def test_ema_trailing_stop():
    """原文：Position Trailing = 10 EMA (short-term) or 20 EMA (primary)"""
    manager = ExitManager()
    # 假设 EMA20 = 95，追踪止损
    trailing = manager.calculate_trailing_stop(
        highest_price=110.0,
        ema10=108.0,
        ema20=107.0,
        scenario="trailing"
    )
    assert trailing == 107.0  # 20 EMA 追踪


def test_100pct_trim_signal():
    """原文：Up 100%+ from base → heavy trim"""
    manager = ExitManager()
    entry = 100.0
    current = 210.0  # 110% gain
    should_trim, reason = manager.should_trim(entry, current, reason="exhaustion")
    assert should_trim is True
    assert "100%+" in reason


def test_breaks_below_20ema_full_exit():
    """原文：Price decisively breaks below 20 EMA → full exit"""
    manager = ExitManager()
    decision = manager.should_exit(
        current_price=95.0,
        ema20=100.0,
        scenario="passive"
    )
    assert decision.should_exit is True
    assert decision.exit_reason == ExitReason.PASSIVE_EXIT


def test_fixed_stop_triggered():
    """固定止损触发"""
    manager = ExitManager()
    # fixed_stop = 100 * 0.98 = 98.0
    # To test FIXED_STOP: current must be ABOVE ema20 (so PASSIVE_EXIT doesn't trigger first)
    # but BELOW fixed_stop
    decision = manager.should_exit(
        current_price=97.5,   # 跌破 98.0 (100 - 2%)
        ema20=96.0,          # 97.5 > 96.0, so doesn't trigger PASSIVE_EXIT first
        entry_price=100.0,
    )
    assert decision.should_exit is True
    assert decision.exit_reason == ExitReason.FIXED_STOP


def test_time_stop():
    """时间止损：持有60天涨幅不足5%"""
    manager = ExitManager()
    decision = manager.should_exit(
        current_price=102.0,  # 持有60天后只有2%涨幅
        ema20=100.0,
        entry_price=100.0,
        days_held=60,
    )
    assert decision.should_exit is True
    assert decision.exit_reason == ExitReason.TIME_STOP


def test_no_exit_healthy_position():
    """健康持仓不触发任何出场"""
    manager = ExitManager()
    decision = manager.should_exit(
        current_price=150.0,
        ema20=120.0,
        entry_price=100.0,
        highest_price=155.0,
        days_held=20,
    )
    assert decision.should_exit is False


def test_trim_ratio_100_to_200():
    """100-200% gain: trim 50%"""
    manager = ExitManager()
    ratio = manager.get_trim_ratio(entry_price=100, current_price=200, highest_price=200)
    assert ratio == 0.50


def test_trim_ratio_200_plus():
    """200%+ gain: trim 75%"""
    manager = ExitManager()
    ratio = manager.get_trim_ratio(entry_price=100, current_price=300, highest_price=300)
    assert ratio == 0.75


def test_trim_ratio_below_100():
    """100%以下不减仓"""
    manager = ExitManager()
    ratio = manager.get_trim_ratio(entry_price=100, current_price=150, highest_price=150)
    assert ratio == 0.0


def test_exit_decision_dataclass():
    """ExitDecision dataclass fields"""
    decision = ExitDecision(
        should_exit=True,
        should_trim=False,
        exit_reason=ExitReason.PASSIVE_EXIT,
        reason_text="Test",
        exit_shares_pct=1.0,
    )
    assert decision.should_exit is True
    assert decision.exit_reason == ExitReason.PASSIVE_EXIT


def test_exit_reason_enum_complete():
    """ExitReason enum should have all values"""
    reasons = list(ExitReason)
    assert ExitReason.FIXED_STOP in reasons
    assert ExitReason.TRAILING_STOP in reasons
    assert ExitReason.ACTIVE_TRIM in reasons
    assert ExitReason.PASSIVE_EXIT in reasons
    assert ExitReason.FAILED_BREAKOUT in reasons
    assert ExitReason.TIME_STOP in reasons
    assert ExitReason.EXHAUSTION in reasons