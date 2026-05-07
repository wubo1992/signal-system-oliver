"""
strategies/v_oliver_kell/exit_manager.py

出场管理（原文 Section 6.3 Stop Loss + Section 6.4 Exit Rules）：

Active Trim Signals（主动止盈）：
    - Up 100%+ from base → heavy trim
    - Exhaustion Extension characteristics → start trimming
    - Before earnings → active trim
    - "Trim into strength, don't sell into weakness"

Passive Stop Signals（被动止损）：
    - Price decisively breaks below 20 EMA → full exit
    - Failed breakout → stop without hesitation
    - Same stock traps you 3 times → exit
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class ExitReason(Enum):
    FIXED_STOP = "fixed_stop"          # 固定止损
    TRAILING_STOP = "trailing_stop"    # 追踪止损
    ACTIVE_TRIM = "active_trim"        # 主动减仓
    PASSIVE_EXIT = "passive_exit"      # 跌破 EMA 全出
    FAILED_BREAKOUT = "failed_breakout"  # 假突破止损
    TIME_STOP = "time_stop"            # 时间止损
    EXHAUSTION = "exhaustion"          # Exhaustion Extension


@dataclass
class ExitDecision:
    should_exit: bool = False
    should_trim: bool = False
    exit_reason: ExitReason | None = None
    reason_text: str = ""
    exit_shares_pct: float = 0.0  # 减仓比例（0-1）


class ExitManager:
    """
    Oliver Kell 出场管理体系。

    原文 Stop Loss Rules（Table）：
        Wedge Pop:      Below breakout day closing low
        EMA Crossback: Below pullback day low
        Base n' Break: Below base range low
        Trailing:       10 EMA (strong) / 20 EMA (primary)

    原文 Exit Rules：
        Active Trim: 100%+, Exhaustion Ext, earnings before
        Passive Stop: breaks 20 EMA, failed breakout, 3x trapped
    """

    # 初始止损百分比（原文 1-2%）
    INITIAL_STOP_PCT = 0.02

    # 追踪止损 EMA 基准
    TRAILING_EMA_PERIOD = 20

    # 涨幅超过多少开始 trim（原文 100%+）
    TRIM_GAIN_THRESHOLD = 1.0  # 100%

    def __init__(self, trailing_ema_period: int = 20):
        self.TRAILING_EMA_PERIOD = trailing_ema_period

    def calculate_stop(self, entry_price: float, scenario: str = "wedge_pop") -> float:
        """
        计算初始止损价。

        原文：
            Wedge Pop:     Below breakout day closing low
            EMA Crossback: Below pullback day low
            Base n' Break: Below base range low
        """
        return round(entry_price * (1 - self.INITIAL_STOP_PCT), 2)

    def calculate_trailing_stop(
        self,
        highest_price: float,
        ema10: float,
        ema20: float,
        scenario: str = "trailing"
    ) -> float:
        """
        计算追踪止损。

        原文 Table：
            - Position Trailing: 10 EMA (when short-term trend strong)
                                 20 EMA (primary trailing stop)
        """
        # 取 20 EMA 作为主追踪止损
        return round(ema20, 2)

    def should_trim(
        self,
        entry_price: float,
        current_price: float,
        reason: str = ""
    ) -> Tuple[bool, str]:
        """
        判断是否应该主动减仓。

        原文 Active Trim Signals：
            - Up 100%+ from base → heavy trim
            - Exhaustion Extension characteristics → start trimming
            - Before earnings → active trim
        """
        if entry_price <= 0:
            return False, ""

        gain_pct = (current_price - entry_price) / entry_price

        trim_reasons = []

        # 涨幅 100%+
        if gain_pct >= self.TRIM_GAIN_THRESHOLD:
            trim_reasons.append("100%+ gain")

        # Exhaustion Extension
        if "exhaustion" in reason.lower():
            trim_reasons.append("Exhaustion Extension")

        # 财报前
        if "earnings" in reason.lower():
            trim_reasons.append("Before earnings")

        if trim_reasons:
            return True, f"Trim: {', '.join(trim_reasons)}"

        return False, ""

    def should_exit(
        self,
        current_price: float,
        ema20: float,
        scenario: str = "passive",
        entry_price: float = 0.0,
        highest_price: float = 0.0,
        days_held: int = 0,
    ) -> ExitDecision:
        """
        判断是否应该全出。

        原文 Passive Stop Signals：
            - Price decisively breaks below 20 EMA → full exit
            - Failed breakout (breaks out then immediately reverses) → stop
            - Same stock traps you 3 times with no progress → wrong timing, exit
        """
        decision = ExitDecision()

        # 1. 跌破 20 EMA → 全出（原文最明确规则）
        if current_price < ema20:
            decision.should_exit = True
            decision.exit_reason = ExitReason.PASSIVE_EXIT
            decision.reason_text = (
                f"Price ${current_price:.2f} decisively below 20 EMA ${ema20:.2f} → full exit"
            )
            return decision

        # 2. 初始止损触发（跌破入场价 - 2%）
        if entry_price > 0:
            fixed_stop = entry_price * (1 - self.INITIAL_STOP_PCT)
            if current_price <= fixed_stop:
                decision.should_exit = True
                decision.exit_reason = ExitReason.FIXED_STOP
                decision.reason_text = (
                    f"Fixed stop: ${current_price:.2f} <= ${fixed_stop:.2f} (entry -2%)"
                )
                return decision

        # 3. 追踪止损（从最高点回落一定比例）
        if highest_price > 0 and ema20 > 0:
            trailing_stop = self.calculate_trailing_stop(
                highest_price, 0, ema20, "trailing"
            )
            if current_price <= trailing_stop:
                gain = (highest_price / entry_price - 1) * 100 if entry_price > 0 else 0
                decision.should_exit = True
                decision.exit_reason = ExitReason.TRAILING_STOP
                decision.reason_text = (
                    f"Trailing stop: ${current_price:.2f} <= ${trailing_stop:.2f} "
                    f"(from high ${highest_price:.2f}, +{gain:.1f}%)"
                )
                return decision

        # 4. 时间止损（持有太久且涨幅不足）
        if days_held >= 60:  # Oliver Kell 没有明确说天数，这里用 60 天
            if entry_price > 0:
                gain = (current_price - entry_price) / entry_price
                if gain < 0.05:  # 持有 60 天涨幅不足 5%
                    decision.should_exit = True
                    decision.exit_reason = ExitReason.TIME_STOP
                    decision.reason_text = (
                        f"Time stop: held {days_held} days, gain {gain*100:.1f}% < 5%"
                    )
                    return decision

        return decision

    def get_trim_ratio(
        self,
        entry_price: float,
        current_price: float,
        highest_price: float
    ) -> float:
        """
        计算应该减仓的比例。

        原文：
            - 100-200% gain: trim 50%
            - 200%+ gain: trim 75%
        """
        if entry_price <= 0:
            return 0.0

        gain_pct = (current_price - entry_price) / entry_price

        if gain_pct >= 2.0:   # 200%+
            return 0.75  # trim 75%
        elif gain_pct >= 1.0:  # 100-200%
            return 0.50  # trim 50%
        return 0.0