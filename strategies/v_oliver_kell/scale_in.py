"""
strategies/v_oliver_kell/scale_in.py

分批建仓逻辑（原文 Section 6.2 Scale-In Method）：

原文：
    Batch 1 (15% position):
    → Entry: Price supported at 20 EMA / Wedge Pop pivot
    → Stop: 1-2% below entry
    → Account risk: ~15-30bps (minimal risk)

    Batch 2 (+15% = 30% total):
    → Condition: Batch 1 profitable, follow-through confirmation next day
    → Simultaneously raise stop to "follow-through day" low
    → Total account risk still ~20-30bps
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BatchState(Enum):
    NONE = "none"
    BATCH1_OPEN = "batch1_open"      # Batch 1 已入场
    BATCH2_OPEN = "batch2_open"      # Batch 2 已入场（30%）
    FULL_POSITION = "full_position"   # 后续加仓已达上限


@dataclass
class PositionBatch:
    """单只股票的分批持仓状态"""
    symbol: str
    batch1_entry_price: float
    batch1_entry_date: datetime
    batch1_stop: float
    batch1_shares: int = 0

    batch2_entry_price: float = 0.0
    batch2_entry_date: datetime | None = None
    batch2_stop: float = 0.0
    batch2_shares: int = 0

    follow_through_low: float = 0.0  # Batch 2 确认日的最低价（新的止损参考）

    highest_price: float = 0.0
    current_stage: str = "wedge_pop"

    def total_shares(self) -> int:
        return self.batch1_shares + self.batch2_shares

    def total_cost(self) -> float:
        return (self.batch1_entry_price * self.batch1_shares +
                self.batch2_entry_price * self.batch2_shares)

    def avg_cost(self) -> float:
        total = self.total_shares()
        if total == 0:
            return 0.0
        return self.total_cost() / total


class ScaleInManager:
    """
    管理分批建仓逻辑。

    核心规则：
        Batch 1: 15%，Wedge Pop 突破时入场，止损 = 突破日收盘低 - 1-2%
        Batch 2: +15%，次日确认后加仓，止损 = 确认日最低价
        后续：可根据 Base n' Break 继续加仓
    """

    BATCH1_PCT = 0.15    # 15%
    BATCH2_PCT = 0.15    # +15% = 30% total
    INITIAL_STOP_PCT = 0.02  # 2% below entry（原文 1-2%）

    def __init__(self):
        self.positions: dict[str, PositionBatch] = {}

    def on_wedge_pop(self, symbol: str, entry_price: float, stop_loss: float,
                     entry_date: datetime | None = None) -> PositionBatch:
        """
        Batch 1 入场（Wedge Pop）。

        原文：
            - Initial position: 15% of account
            - Stop: 1-2% below entry
        """
        if entry_date is None:
            entry_date = datetime.utcnow()

        # 初始止损：entry_price * (1 - 2%)
        initial_stop = round(entry_price * (1 - self.INITIAL_STOP_PCT), 2)

        batch = PositionBatch(
            symbol=symbol,
            batch1_entry_price=entry_price,
            batch1_entry_date=entry_date,
            batch1_stop=initial_stop,
            highest_price=entry_price,
            current_stage="wedge_pop",
        )
        self.positions[symbol] = batch
        return batch

    def on_follow_through(self, symbol: str, follow_through_low: float,
                          entry_date: datetime | None = None,
                          batch2_entry_price: float | None = None) -> PositionBatch | None:
        """
        Batch 2 加仓（次日确认 Follow-through）。

        原文：
            - Batch 1 profitable, follow-through confirmation next day
            - Simultaneously raise stop to "follow-through day" low
        """
        batch = self.positions.get(symbol)
        if batch is None:
            return None

        if entry_date is None:
            entry_date = datetime.utcnow()

        # Batch 1 必须已盈利
        if batch.highest_price <= batch.batch1_entry_price:
            return None

        # 更新 Batch 2 信息
        batch.batch2_entry_date = entry_date
        batch.batch2_entry_price = batch2_entry_price or follow_through_low
        batch.batch2_stop = follow_through_low
        batch.follow_through_low = follow_through_low
        batch.current_stage = "ema_crossback"

        return batch

    def on_base_break(self, symbol: str, entry_price: float,
                       entry_date: datetime | None = None) -> PositionBatch | None:
        """
        Base n' Break 继续加仓。

        原文：
            - Can add small during consolidation, full size at breakout
            - This pattern can repeat multiple times
        """
        batch = self.positions.get(symbol)
        if batch is None:
            return None

        if entry_date is None:
            entry_date = datetime.utcnow()

        batch.current_stage = "base_n_break"
        return batch

    def update_highest_price(self, symbol: str, current_price: float) -> None:
        """更新持仓最高价"""
        batch = self.positions.get(symbol)
        if batch:
            if current_price > batch.highest_price:
                batch.highest_price = current_price

    def get_batch_state(self, symbol: str) -> BatchState:
        """获取当前批次状态"""
        batch = self.positions.get(symbol)
        if batch is None:
            return BatchState.NONE
        if batch.batch2_entry_date is None:
            return BatchState.BATCH1_OPEN
        return BatchState.BATCH2_OPEN

    def get_stop(self, symbol: str) -> float:
        """获取当前止损价"""
        batch = self.positions.get(symbol)
        if batch is None:
            return 0.0
        state = self.get_batch_state(symbol)
        if state == BatchState.BATCH1_OPEN:
            return batch.batch1_stop
        elif state == BatchState.BATCH2_OPEN:
            # Batch 2 后止损上移至 follow-through low
            return batch.follow_through_low or batch.batch2_stop
        return 0.0

    def get_position_pct(self, symbol: str) -> float:
        """
        获取持仓百分比。

        原文：
            Batch 1 = 15%
            Batch 2 = +15% = 30% total
        """
        state = self.get_batch_state(symbol)
        if state == BatchState.NONE:
            return 0.0
        elif state == BatchState.BATCH1_OPEN:
            return self.BATCH1_PCT * 100  # 15%
        elif state == BatchState.BATCH2_OPEN:
            return (self.BATCH1_PCT + self.BATCH2_PCT) * 100  # 30%
        return 0.0

    def should_add_batch2(self, symbol: str) -> bool:
        """
        判断是否可以加 Batch 2。

        原文 Condition：
            - Batch 1 profitable
            - follow-through confirmation next day
        """
        batch = self.positions.get(symbol)
        if batch is None:
            return False
        if batch.batch2_entry_date is not None:
            return False  # Batch 2 已完成
        # Batch 1 盈利
        return batch.highest_price > batch.batch1_entry_price

    def to_dict(self, symbol: str) -> dict | None:
        """将持仓状态序列化为 dict（用于 positions.json）"""
        batch = self.positions.get(symbol)
        if batch is None:
            return None
        return {
            "symbol": batch.symbol,
            "batch_1_entry_price": batch.batch1_entry_price,
            "batch_1_entry_date": batch.batch1_entry_date.isoformat() if batch.batch1_entry_date else None,
            "batch_1_shares": batch.batch1_shares,
            "batch_1_stop": batch.batch1_stop,
            "batch_2_entry_price": batch.batch2_entry_price,
            "batch_2_entry_date": batch.batch2_entry_date.isoformat() if batch.batch2_entry_date else None,
            "batch_2_shares": batch.batch2_shares,
            "batch_2_stop": batch.batch2_stop,
            "follow_through_low": batch.follow_through_low,
            "highest_price": batch.highest_price,
            "current_stage": batch.current_stage,
            "avg_cost": batch.avg_cost(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> PositionBatch:
        """从 dict 反序列化"""
        batch = PositionBatch(
            symbol=data["symbol"],
            batch1_entry_price=data["batch_1_entry_price"],
            batch1_entry_date=datetime.fromisoformat(data["batch_1_entry_date"]) if data.get("batch_1_entry_date") else None,
            batch1_shares=data.get("batch_1_shares", 0),
            batch1_stop=data.get("batch_1_stop", 0.0),
            batch2_entry_price=data.get("batch_2_entry_price", 0.0),
            batch2_entry_date=datetime.fromisoformat(data["batch_2_entry_date"]) if data.get("batch_2_entry_date") else None,
            batch2_shares=data.get("batch_2_shares", 0),
            batch2_stop=data.get("batch_2_stop", 0.0),
            follow_through_low=data.get("follow_through_low", 0.0),
            highest_price=data.get("highest_price", 0.0),
            current_stage=data.get("current_stage", "unknown"),
        )
        return batch