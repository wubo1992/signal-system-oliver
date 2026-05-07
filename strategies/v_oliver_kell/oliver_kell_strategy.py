"""
strategies/v_oliver_kell/oliver_kell_strategy.py — Oliver Kell Cycle of Price Action 主策略

继承 StrategyBase，实现完整六阶段入场/出场逻辑。

入场（买入信号）：
    ① Reversal Extension — 不买，只观察
    ② Wedge Pop         — 15% 建仓，最佳买点
    ③ EMA Crossback     — 回踩 EMA，+15% 至 30%
    ④ Base n' Break     — 盘整后突破，可加仓

出场（卖出信号）：
    - 固定止损：2% below entry
    - 追踪止盈：跌破 20 EMA
    - 主动减仓：100%+ 涨幅后分批卖
    - 时间止损：60天持有涨幅不足5%

市场环境过滤：
    - Quality:  指数 > 20 EMA → 正常操作
    - Average:  指数 ≈ 20 EMA → 降仓
    - Poor:     指数 < 20 EMA → 1-2成仓，最多30%
    - Hostile:  指数持续下跌 → 空仓
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from events import EventQueue, SignalEvent
from strategies.base import StrategyBase
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage
from strategies.v_oliver_kell.wedge_finder import WedgeFinder
from strategies.v_oliver_kell.market_environment import MarketEnvironment, MarketState
from strategies.v_oliver_kell.scale_in import ScaleInManager, BatchState
from strategies.v_oliver_kell.exit_manager import ExitManager


@dataclass
class OKPosition:
    """Oliver Kell 策略持仓状态"""
    symbol: str
    entry_price: float
    entry_date: datetime
    highest_price: float
    shares: int = 0
    batch_state: BatchState = BatchState.NONE
    current_stage: str = "unknown"
    days_held: int = 0
    times_trapped: int = 0


class OliverKellStrategy(StrategyBase):
    """
    Oliver Kell Cycle of Price Action 策略。

    核心特征：
        - 基于 10/20 EMA 的六阶段价格周期
        - Wedge Pop 最佳买点（15%）
        - EMA Crossback 加仓至 30%
        - 市场环境自动过滤
        - 分批建仓 + 主动减仓出场
    """

    strategy_id = "v_oliver_kell"
    strategy_name = "Oliver Kell Cycle of Price Action"

    def __init__(
        self,
        strategy_config: dict,
        market_data: dict[str, pd.DataFrame],
        live_mode: bool = False,
    ) -> None:
        super().__init__(strategy_config, market_data)
        self.live_mode = live_mode

        # 子模块
        self.cycle_detector = CycleDetector(
            wedge_lookback=self.cfg.get("wedge_lookback", 20),
            base_lookback=self.cfg.get("base_lookback", 20),
        )
        self.wedge_finder = WedgeFinder(
            lookback=self.cfg.get("wedge_lookback", 20),
        )
        self.market_env = MarketEnvironment(
            index_symbol=self.cfg.get("index_symbol", "QQQ"),
        )
        self.scale_in = ScaleInManager()
        self.exit_mgr = ExitManager()

        # 持仓
        self.positions: dict[str, OKPosition] = {}

    def run_date(self, date: datetime, queue: EventQueue) -> list[SignalEvent]:
        """
        每日策略执行主循环。

        顺序：
            1. 分析市场环境（QQQ 20 EMA）
            2. 检查持仓出场
            3. 扫描个股找买入信号
        """
        signals = []

        # Step 1: 市场环境
        index_df = self._get_index_data()
        market_state = self.market_env.classify(index_df)
        max_position_pct = self.market_env.max_position_pct(market_state)

        # Step 2: 检查持仓出场
        exit_signals = self._check_exits(date, market_state)
        for sig in exit_signals:
            queue.put(sig)
            signals.append(sig)

        # Step 3: 找买入信号（受市场环境限制）
        if market_state != MarketState.HOSTILE:
            buy_signals = self._find_buy_signals(date, market_state, max_position_pct)
            for sig in buy_signals:
                queue.put(sig)
                signals.append(sig)

        return signals

    def _get_index_data(self) -> pd.DataFrame:
        """获取指数数据（QQQ）"""
        index_symbol = self.cfg.get("index_symbol", "QQQ")
        return self.market_data.get(index_symbol, pd.DataFrame())

    def _check_exits(self, date: datetime, market_state: MarketState) -> list[SignalEvent]:
        """检查所有持仓的出场信号"""
        signals = []
        to_close = []

        index_df = self._get_index_data()
        if not index_df.empty and "EMA20" in index_df.columns:
            ema20 = float(index_df["EMA20"].iloc[-1])
        else:
            ema20 = 0.0

        for symbol, pos in list(self.positions.items()):
            df = self.market_data.get(symbol)
            if df is None or df.empty:
                continue

            df_to_date = self._slice_to_date(df, date)
            if df_to_date.empty:
                continue

            current_price = float(df_to_date["close"].iloc[-1])
            pos.days_held += 1
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # 更新 scale_in manager
            if symbol in self.scale_in.positions:
                self.scale_in.update_highest_price(symbol, current_price)

            # 出场判断
            decision = self.exit_mgr.should_exit(
                current_price=current_price,
                ema20=ema20,
                scenario="passive",
                entry_price=pos.entry_price,
                highest_price=pos.highest_price,
                days_held=pos.days_held,
            )

            if decision.should_exit:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=5,
                    reason=decision.reason_text,
                    stop_loss=None,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # 主动减仓检查（100%+）
            should_trim, trim_reason = self.exit_mgr.should_trim(
                entry_price=pos.entry_price,
                current_price=current_price,
                reason="",
            )
            if should_trim:
                trim_ratio = self.exit_mgr.get_trim_ratio(
                    pos.entry_price, current_price, pos.highest_price
                )
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=3,
                    reason=f"Active trim {trim_ratio*100:.0f}%: {trim_reason}",
                    stop_loss=None,
                    shares=int(pos.shares * trim_ratio) if pos.shares > 0 else 0,
                )
                signals.append(sig)
                # 更新持仓（不关闭，只是减仓）
                if pos.shares > 0:
                    pos.shares = int(pos.shares * (1 - trim_ratio))

        for symbol in to_close:
            del self.positions[symbol]
            if symbol in self.scale_in.positions:
                del self.scale_in.positions[symbol]

        return signals

    def _find_buy_signals(
        self,
        date: datetime,
        market_state: MarketState,
        max_position_pct: float,
    ) -> list[SignalEvent]:
        """扫描个股找买入信号"""
        signals = []

        for symbol, df in self.market_data.items():
            if symbol in ("SPY", "^VIX", "QQQ"):
                continue
            if symbol in self.positions:
                continue  # 已有持仓

            df_to_date = self._slice_to_date(df, date)
            min_rows = 60
            if len(df_to_date) < min_rows:
                continue

            signal = self._check_entry(symbol, df_to_date, date, market_state)
            if signal:
                signals.append(signal)

        # 按信号强度排序
        signals.sort(key=lambda s: s.data["strength"], reverse=True)

        # 取前 N 个（根据市场环境）
        if market_state == MarketState.POOR:
            max_signals = 2
        elif market_state == MarketState.AVERAGE:
            max_signals = 5
        else:
            max_signals = 7

        return signals[:max_signals]

    def _check_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        market_state: MarketState,
    ) -> SignalEvent | None:
        """
        检查个股是否满足买入条件。

        买入信号（按原文优先级）：
            1. Wedge Pop（最佳买点）
            2. EMA Crossback（回踩加仓）
            3. Base n' Break（趋势延续）
        """
        close = float(df["close"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])

        # 识别当前阶段
        stage = self.cycle_detector.classify(df)

        # Wedge Pop
        if stage == CycleStage.WEDGE_POP:
            return self._handle_wedge_pop(symbol, df, date, close, ema10, ema20, stage)

        # EMA Crossback
        if stage == CycleStage.EMA_CROSSBACK:
            return self._handle_ema_crossback(symbol, df, date, close, stage)

        # Base n' Break
        if stage == CycleStage.BASE_N_BREAK:
            return self._handle_base_n_break(symbol, df, date, close, stage)

        return None

    def _handle_wedge_pop(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        ema10: float,
        ema20: float,
        stage: CycleStage,
    ) -> SignalEvent:
        """
        Wedge Pop 入场。

        原文：
            - Initial position: 15% of account
            - Stop: Below breakout day closing low
            - Best risk/reward entry in the entire cycle
        """
        stop = self.wedge_finder.get_breakout_stop(df)
        if stop == 0.0:
            stop = round(close * (1 - 0.02), 2)  # fallback: 2% below close

        # 记录持仓
        position = OKPosition(
            symbol=symbol,
            entry_price=close,
            entry_date=date,
            highest_price=close,
            shares=0,
            batch_state=BatchState.BATCH1_OPEN,
            current_stage="wedge_pop",
        )
        self.positions[symbol] = position

        # 触发 scale_in
        self.scale_in.on_wedge_pop(symbol, close, stop, date)

        reason = (
            f"[Wedge Pop] Best entry | "
            f"[EMA] 10={ema10:.1f}, 20={ema20:.1f} | "
            f"[Stage] {stage.value}"
        )

        return SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=5,
            reason=reason,
            stop_loss=stop,
        )

    def _handle_ema_crossback(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        stage: CycleStage,
    ) -> SignalEvent | None:
        """
        EMA Crossback 入场/加仓。

        原文：
            - Scale to 30% total (combine with Wedge Pop position)
            - Stop: Below pullback day low
            - Account risk remains ~20-30bps
        """
        # 必须是已有 Wedge Pop 持仓的股票
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        if pos.batch_state != BatchState.BATCH1_OPEN:
            return None

        # 检查是否应该加 Batch 2
        if not self.scale_in.should_add_batch2(symbol):
            return None

        # 当天最低价（止损参考）
        today_low = float(df["low"].iloc[-1])
        stop = round(today_low * (1 - 0.02), 2)

        # 更新持仓状态
        pos.batch_state = BatchState.BATCH2_OPEN
        pos.current_stage = "ema_crossback"

        # 触发 scale_in Batch 2
        self.scale_in.on_follow_through(symbol, follow_through_low=today_low)

        reason = (
            f"[EMA Crossback] Add to 30% | "
            f"[Stop] ${stop:.2f} | "
            f"[Stage] {stage.value}"
        )

        return SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=4,
            reason=reason,
            stop_loss=stop,
        )

    def _handle_base_n_break(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        stage: CycleStage,
    ) -> SignalEvent | None:
        """
        Base n' Break 入场/加仓。

        原文：
            - Can add small during consolidation, full size at breakout
            - This pattern can repeat multiple times
        """
        # 基本过滤：必须先有 Wedge Pop 才能 Base n' Break
        if self.cfg.get("require_wedge_pop_first", True):
            if symbol not in self.positions:
                return None  # 必须先有 Wedge Pop

        pos = self.positions.get(symbol)
        if pos and pos.batch_state == BatchState.BATCH2_OPEN:
            return None  # 30% 已满，不再加

        # 盘整区间止损
        base_low = float(df["low"].iloc[-21:].min())
        stop = round(base_low * (1 - 0.02), 2)

        reason = (
            f"[Base n' Break] Continuation | "
            f"[Base Low] ${base_low:.2f} | "
            f"[Stage] {stage.value}"
        )

        return SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=3,
            reason=reason,
            stop_loss=stop,
        )

    def _slice_to_date(self, df: pd.DataFrame, date: datetime) -> pd.DataFrame:
        """切片到指定日期"""
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        idx = df.index
        if idx.tzinfo is None:
            idx = idx.tz_localize("UTC")
            df = df.copy()
            df.index = idx
        return df[df.index <= date]

    def get_open_positions(self) -> dict[str, OKPosition]:
        return dict(self.positions)