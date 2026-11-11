"""
tests/signals/test_console_watchlist_stop.py

回归测试：控制台打印的观望行「参考止损」必须带 $ 前缀（与买入/做空行一致）。
"""
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from events import EventType, SignalEvent
from signals.generator import _print_table


def _watchlist_event(stop_loss=36.62, reason="[Base Tightening] Price above EMA20"):
    return SignalEvent(
        type=EventType.SIGNAL,
        symbol="ASX",
        timestamp=datetime(2026, 11, 11, tzinfo=timezone.utc),
        data={
            "direction": "watch",
            "strength": 2,
            "reason": reason,
            "stop_loss": stop_loss,
            "volume_ratio": 1.4,
            "rs_value_10d": 0.8652,
            "rs_value": 0.7734,
            "rs_value_10w": 0.9824,
            "rs_rating": 91,
            "rs_ratio": 2.0893,
            "weinstein_stage": "Stage 3 做顶 · 3B 顶部后期",
        },
    )


def test_watchlist_stop_loss_prints_with_dollar_sign(capsys):
    """观望行的参考止损是裸 float，打印时必须补 $（CSV 里本来就是 '$36.62'）。"""
    _print_table([], watchlist_records=[_watchlist_event()])
    out = capsys.readouterr().out

    assert "$36.62" in out
    assert " 36.62" not in out.replace("$36.62", "")
