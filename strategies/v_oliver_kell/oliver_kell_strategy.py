"""
strategies/v_oliver_kell/oliver_kell_strategy.py — Oliver Kell Cycle of Price Action 主策略

继承 StrategyBase，实现完整六阶段入场/出场逻辑。

入场（买入信号）：
    ① Reversal Extension — 不买，只观察
    ② Wedge Pop         — 30% 建仓，最佳买点
    ③ EMA Crossback     — 回踩 EMA，+10% 至 40%
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
from strategies.v_oliver_kell.weinstein_stage import compute_weinstein_detail


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
    # Failed Breakout 追踪
    breakout_price: float = 0.0  # 突破价位（用于检测假突破）
    breakout_date: datetime | None = None
    # Ignite Bar 追踪（用于动态调整止损）
    ignite_bar_low: float = 0.0  # 持仓期间最低的 Ignite Bar low
    # Extension 追踪（日K线操作）
    extension_count: int = 0  # Extension次数
    highest_extension_price: float = 0.0  # 当前Extension期间最高价
    ema10_at_extension_start: float = 0.0  # 当前 extension 开始时的 EMA10
    # Extension内分段卖出
    last_sell_reference_price: float = 0.0  # 上次减仓参考价（用于计算下次回落5%）
    # EMA-based trailing stop 追踪
    trailing_stop_price: float = 0.0  # 动态追踪止损（跟随 EMA）
    # 入场时的关键支撑低点（PDF: breakout day low / pullback day low / base range low）
    # 这是绝对止损锚点，不是 entry_price 的百分比
    entry_stop_price: float = 0.0


class OliverKellStrategy(StrategyBase):
    """
    Oliver Kell Cycle of Price Action 策略。

    核心特征：
        - 基于 10/20 EMA 的六阶段价格周期
        - Wedge Pop 最佳买点（30% Top Idea）
        - EMA Crossback 加仓至 40%
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
        oneil_rs_map: dict[str, tuple[int | None, float | None]] | None = None,
    ) -> None:
        super().__init__(strategy_config, market_data)
        self.live_mode = live_mode

        # O'Neil RS 评级横截面表（由 oneil_rs.compute_oneil_rs_map 预先算好）
        self._oneil_rs_map = oneil_rs_map or {}

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

        # 追踪最近有 Wedge Pop 的股票（用于 require_wedge_pop_first 过滤）
        self._recent_wedge_pop_stocks: set[str] = set()

    def run_date(self, date: datetime, queue: EventQueue) -> list[SignalEvent]:
        """
        每日策略执行主循环。

        顺序：
            1. 分析市场环境 + QQQ Cycle Stage
            2. 检查持仓出场
            3. 扫描个股找买入信号（受 Index Cycle 限制）
        """
        signals = []

        # Step 1: 市场环境 + QQQ Cycle Stage
        index_df = self._get_index_data()
        market_state = self.market_env.classify(index_df)
        max_position_pct = self.market_env.max_position_pct(market_state)

        # === QQQ Cycle Stage 检测 ===
        index_cycle_stage = CycleStage.UNKNOWN
        if len(index_df) >= 25:
            index_cycle_stage = self.cycle_detector.classify(index_df)

        # === 根据 Index Cycle Stage 调整仓位 ===
        # 原文 Section 7.1：
        # - Index Wedge Pop → 积极寻找领头羊
        # - Index EMA Crossback → 个股入场
        # - Index Base n' Break → 最强阶段，满仓
        # - Index Exhaustion Extension → 开始防御，锁定利润
        # - Index Wedge Drop → 退出/轻仓，等待新周期
        index_buy_bias = True
        if index_cycle_stage == CycleStage.WEDGE_DROP:
            # 指数下降确认：不开新仓
            index_buy_bias = False
        elif index_cycle_stage == CycleStage.EXHAUSTION_EXTENSION:
            # 指数顶部警告：减少新买入，严格选股
            max_position_pct = min(max_position_pct, 0.5)
        elif index_cycle_stage == CycleStage.BASE_N_BREAK:
            # 指数最强阶段：可以满仓操作
            max_position_pct = max_position_pct

        # Step 2: 找买入信号（受市场环境和 Index Cycle 限制）
        if market_state != MarketState.HOSTILE and index_buy_bias:
            buy_signals = self._find_buy_signals(date, market_state, max_position_pct, self._recent_wedge_pop_stocks)
            buy_signals.sort(key=lambda s: s.data["strength"], reverse=True)
            for sig in buy_signals:
                self._attach_weinstein_stage(sig, date)
                queue.put(sig)
                signals.append(sig)
                # 追踪 Wedge Pop 信号（用于 require_wedge_pop_first 过滤）
                if sig.data.get("cycle_stage") == "wedge_pop":
                    self._recent_wedge_pop_stocks.add(sig.symbol)

        # Step 3: 扫描做空信号（所有触发 Wedge Drop 或 Exhaustion Extension 的股票）
        short_signals = self._find_short_signals(date, market_state)
        for sig in short_signals:
            self._attach_weinstein_stage(sig, date)
            queue.put(sig)
            signals.append(sig)

        return signals

    def _get_index_data(self) -> pd.DataFrame:
        """获取指数数据（QQQ），并计算 EMA 列"""
        index_symbol = self.cfg.get("index_symbol", "QQQ")
        df = self.market_data.get(index_symbol, pd.DataFrame()).copy()
        if not df.empty and "close" in df.columns:
            df["EMA10"] = df["close"].ewm(span=10).mean()
            df["EMA20"] = df["close"].ewm(span=20).mean()
        return df

    def _get_rs_benchmark_df(self) -> pd.DataFrame:
        """获取 RS 基准（默认 SPY）的行情数据。"""
        benchmark = self.cfg.get("rs_benchmark", "SPY")
        return self.market_data.get(benchmark, pd.DataFrame()).copy()

    def _compute_signal_metrics(self, df: pd.DataFrame) -> tuple[float | None, float | None, float | None, float | None]:
        """
        计算信号层统一的四个关键指标：(RS 10日, RS 20日, RS 10周, 量比)。

        返回：
            (rs_value_10d, rs_value_20d, rs_value_10w, volume_ratio) — 任一指标数据不足时返回 None
        """
        rs_value_10d: float | None = None
        rs_value_20d: float | None = None
        rs_value_10w: float | None = None
        vol_ratio: float | None = None

        benchmark = self._get_rs_benchmark_df()
        short_window = self.cfg.get("rs_short_window", 10)
        # RS 10D（短期窗口，默认 10 个交易日 ≈ 2 周）
        if not benchmark.empty and len(benchmark) >= short_window + 5 and len(df) >= short_window + 5:
            try:
                rs_series_short = self.cycle_detector.compute_rs_line_short(df, benchmark, lookback=short_window)
                if not rs_series_short.empty:
                    rs_value_10d = float(rs_series_short.iloc[-1])
            except Exception:
                rs_value_10d = None

        # RS 20D（默认 20 日窗口）
        if not benchmark.empty and len(benchmark) >= 25 and len(df) >= 25:
            try:
                rs_series = self.cycle_detector.compute_rs_line(df, benchmark)
                if not rs_series.empty:
                    rs_value_20d = float(rs_series.iloc[-1])
            except Exception:
                rs_value_20d = None

        # RS 10W（10 周 ≈ 50 个交易日）
        if not benchmark.empty and len(benchmark) >= 55 and len(df) >= 55:
            try:
                rs_series_long = self.cycle_detector.compute_rs_line_long(df, benchmark, lookback=50)
                if not rs_series_long.empty:
                    rs_value_10w = float(rs_series_long.iloc[-1])
            except Exception:
                rs_value_10w = None

        try:
            vr = self.cycle_detector.compute_volume_ratio(df, lookback=self.cfg.get("volume_ratio_window", 20))
            if vr is not None:
                vol_ratio = float(vr)
        except Exception:
            vol_ratio = None

        return rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio

    @staticmethod
    def _format_rs_note(rs_value: float | None) -> str:
        if rs_value is None:
            return ""
        try:
            return f" | [RS] {rs_value:.4f}"
        except Exception:
            return ""

    @staticmethod
    def _format_rs_long_note(rs_value: float | None) -> str:
        if rs_value is None:
            return ""
        try:
            return f" | [RS-10W] {rs_value:.4f}"
        except Exception:
            return ""

    @staticmethod
    def _format_rs_short_note(rs_value: float | None) -> str:
        if rs_value is None:
            return ""
        try:
            return f" | [RS-10D] {rs_value:.4f}"
        except Exception:
            return ""

    @staticmethod
    def _format_vol_note(vol_ratio: float | None) -> str:
        if vol_ratio is None:
            return ""
        try:
            return f" | [Vol] {vol_ratio:.1f}x"
        except Exception:
            return ""

    def _get_oneil_rs(self, symbol: str) -> tuple[int | None, float | None]:
        """取 O'Neil RS 评级（1-99 百分位）与 RS 倍数（财富指数之比 vs SPY）。"""
        return self._oneil_rs_map.get(symbol, (None, None))

    def _get_weinstein_stage(self, symbol: str, date: datetime) -> dict | None:
        """取 Weinstein 四阶段判断（截至 date），返回阶段详情 dict。

        口径：周线 + 30 周均线的经典结构引擎（WEINSTEIN-STRUCTURE-1.3）。
        数据不足（周线 < 60 根）时返回 None。
        """
        df = self.market_data.get(symbol)
        if df is None or df.empty:
            return None
        return compute_weinstein_detail(self._slice_to_date(df, date), as_of=date)

    def _attach_weinstein_stage(self, sig: SignalEvent, date: datetime) -> None:
        """给信号挂上 Weinstein 阶段（event.data + reason 里的 [WStage] token）。

        阶段是「这只票现在处于中长期趋势的哪一段」的背景信息，
        与 Kell 六阶段的短期形态判断互补：Stage 2 里的 Wedge Pop 才是最强买点。
        """
        detail = self._get_weinstein_stage(sig.symbol, date)
        if not detail:
            return
        label = detail["label"]
        sig.data["weinstein_stage"] = label
        sig.data["weinstein_stage_num"] = detail["stage"]
        sig.data["weinstein_substage"] = detail.get("substage")
        sig.data["weinstein_substage_label"] = detail.get("substage_label")
        sig.data["weinstein_ma30_slope"] = detail.get("ma30_slope_pct")
        sig.data["weinstein_price_vs_ma"] = detail.get("price_vs_ma_pct")
        sig.data["weinstein_weeks_in_stage"] = detail.get("duration_weeks")
        sig.data["weinstein_developing"] = detail.get("is_developing")
        sig.data["weinstein_confirmed_label"] = detail.get("confirmed_label")
        sig.data["weinstein_week_status"] = detail.get("week_status")
        reason = sig.data.get("reason")
        if reason and "[WStage]" not in reason:
            developing = "（发展中）" if detail.get("is_developing") else ""
            sig.data["reason"] = f"{reason} | [WStage] {label}{developing}"

    @staticmethod
    def _format_oneil_rs_note(rs_rating: int | None, rs_ratio: float | None) -> str:
        if rs_rating is None and rs_ratio is None:
            return ""
        parts = []
        if rs_rating is not None:
            parts.append(f" | [RS-Rating] {rs_rating}")
        if rs_ratio is not None:
            try:
                parts.append(f" | [RS-Mult] {rs_ratio:.4f}")
            except Exception:
                pass
        return "".join(parts)

    def _check_exits(self, date: datetime, market_state: MarketState) -> list[SignalEvent]:
        """检查所有持仓的出场信号

        PDF Exit Logic (Page 10, 20, 29, 36):
            - 1st Extension: Reduce from 25-35% to 20-25% (sell ~20%)
            - 2nd Extension: Take more profits (sell 50%)
            - 3rd Extension: Sell all (late in intermediate-term trend)
            - Trail stops with EMA (not fixed %)
            - Close < EMA10/20 = exit

        Exit hierarchy (priority order, PDF-based):
            1. Wedge Drop → sell all
            2. Close < EMA10 → sell all (trailing stop per PDF)
            3. Close < EMA20 * 0.98 → sell all (允许2%穿透)
            4. Failed Breakout → sell all
            5. Candlestick patterns (Shooting Star, Bearish Engulfing, Evening Star Doji) → sell all
            6. Extension partial sell: pullback 5% from Extension high (price >15% above EMA) → sell 20%
        """
        signals = []
        to_close = []

        for symbol, pos in list(self.positions.items()):
            # 兼容处理：旧版 positions.json 存储的是 generic Position，加载后缺少 OKPosition 特有字段
            # 检测并升级为 OKPosition，避免运行时 AttributeError
            if not isinstance(pos, OKPosition):
                pos = OKPosition(
                    symbol=pos.symbol,
                    entry_price=pos.entry_price,
                    entry_date=pos.entry_date,
                    highest_price=pos.highest_price,
                    shares=int(pos.shares) if pos.shares else 0,
                    days_held=pos.days_held,
                    batch_state=BatchState.NONE,
                    current_stage="unknown",
                    times_trapped=0,
                    breakout_price=0.0,
                    breakout_date=None,
                    ignite_bar_low=0.0,
                    extension_count=0,
                    highest_extension_price=0.0,
                    ema10_at_extension_start=0.0,
                    last_sell_reference_price=0.0,
                    trailing_stop_price=0.0,
                    entry_stop_price=0.0,
                )
                self.positions[symbol] = pos

            df = self.market_data.get(symbol)
            if df is None or df.empty:
                continue

            df_to_date = self._slice_to_date(df, date)
            if df_to_date.empty:
                continue

            # 使用 _get_row_for_date 获取正确的当日收盘行（避免 iloc[-1] 返回次日 05:00 bar 的问题）
            row = self._get_row_for_date(df, date)
            if row is None:
                continue
            current_price = float(row["close"])
            # EMA 也基于正确的行计算（使用 row 的位置）
            ema_series = df_to_date["close"].ewm(span=10).mean()
            ema10 = float(ema_series.loc[row.name]) if row.name in ema_series.index else float(ema_series.iloc[-1])
            ema20_series = df_to_date["close"].ewm(span=20).mean()
            ema20 = float(ema20_series.loc[row.name]) if row.name in ema20_series.index else float(ema20_series.iloc[-1])

            pos.days_held += 1
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # 更新 scale_in manager
            if symbol in self.scale_in.positions:
                self.scale_in.update_highest_price(symbol, current_price)

            # === Ignite Bar 检测：追踪持仓期间的 Ignite Bar low ===
            self._detect_and_update_ignite_bar(pos, df_to_date)

            # === 主动上调止损锚点到 Ignite Bar low（PDF Page 48-49）===
            # "when we see an ignition bar low, we want to adjust our stops to the low of that bar"
            # Ignite Bar 低点只上调不下调（一旦提高就不再降低）
            # 使用 getattr 处理旧版本加载的 Position 对象
            if getattr(pos, 'ignite_bar_low', 0.0) > pos.entry_stop_price:
                pos.entry_stop_price = getattr(pos, 'ignite_bar_low', 0.0)

            # === 1. Wedge Drop → sell all ===
            wedge_drop_detected = self.cycle_detector.classify(df_to_date) == CycleStage.WEDGE_DROP
            if wedge_drop_detected:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=5,
                    reason="[Wedge Drop] Downtrend confirmation - exit all",
                    stop_loss=None,
                    cycle_stage="wedge_drop",
                    current_price=current_price,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # === 1.5 Hard Stop: 跌破关键支撑 OR 8% 硬止损 → sell all（PDF Page 17, 20, 47）===
            # 关键支撑（entry_stop_price）和 8% 硬止损取较严格者（更接近入场价）
            # 两者同时生效，哪个先触发就按哪个执行
            stop8pct = pos.entry_price * 0.92
            if pos.entry_stop_price > 0:
                active_stop = max(pos.entry_stop_price, stop8pct)  # 取较严格者
            else:
                active_stop = stop8pct  # 无关键支撑时用 8%

            if current_price < active_stop:
                if pos.entry_stop_price > 0 and current_price < pos.entry_stop_price:
                    reason = f"[Stop Hit] ${current_price:.2f} < key support ${pos.entry_stop_price:.2f}"
                    stage = "stop_hit"
                else:
                    reason = f"[Hard Stop 8%] ${current_price:.2f} < ${stop8pct:.2f}"
                    stage = "hard_stop"
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=5,
                    reason=reason,
                    stop_loss=None,
                    cycle_stage=stage,
                    current_price=current_price,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # === 1.6 EMA10 Break → 只有形成Wedge Drop才卖（不再无条件卖出）===
            # 用户纠正：EMA10 Break不一定是卖出信号
            # 如果只是回踩（没形成Wedge Drop），应该继续持有
            # Wedge Drop已经在line 249检查过了，这里不需要再卖
            # 保留EMA10 Break作为参考，但不触发卖出
            pass  # EMA10 Break不再触发卖出

            # === 1.7 Ignite Bar Low Stop（PDF Page 48-49: "adjust our stops to the low of that bar"）===
            # Ignite Bar 低点被追踪（只上调不下调）。如果价格收盘跌破，则出场
            # 使用 getattr 处理旧版本加载的 Position 对象
            if getattr(pos, 'ignite_bar_low', 0.0) > 0 and current_price < getattr(pos, 'ignite_bar_low', 0.0):
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=4,
                    reason=f"[Ignite Bar Stop] ${current_price:.2f} < Ignite Low ${pos.ignite_bar_low:.2f} - exit",
                    stop_loss=None,
                    cycle_stage="ignite_bar_stop",
                    current_price=current_price,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # === Extension 检测（原文：Extension 次数决定卖出力度）===
            # Extension定义：价格涨幅超过EMA10的10%，即 price > EMA10 * 1.10
            # Extension结束：价格从Extension高点回落5%，触发一次分批卖出后，
            #                只有当价格再次回落至EMA附近（< EMA10 * 1.03），
            #                才判定当前Extension真正结束，下次再超过10%算下一次Extension
            is_extended = current_price > ema10 * 1.10

            if is_extended:
                if pos.extension_count == 0:
                    # 新Extension开始（可能是第1/2/3次）
                    pos.extension_count += 1
                    pos.ema10_at_extension_start = ema10
                    pos.highest_extension_price = current_price
                    pos.last_sell_reference_price = current_price
                elif current_price > pos.highest_extension_price:
                    # 同一个Extension内创新高
                    pos.highest_extension_price = current_price
            elif current_price < ema10 * 1.03 and pos.extension_count > 0:
                # 价格从Extension高点显著回落至EMA附近，当前Extension正式结束
                # 下次再超过15%时，extension_count会再加1（变成2/3/...）
                pos.extension_count = 0



            # === 3. Close < EMA20 * 0.98 → sell all (允许2%穿透) ===
            if current_price < ema20 * 0.98:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=5,
                    reason=f"[EMA20 Break] Close ${current_price:.2f} < EMA20 ${ema20:.2f} - exit all",
                    stop_loss=None,
                    cycle_stage="ema20_break",
                    current_price=current_price,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # === 4. Failed Breakout → sell all ===
            # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
            # 但不再作为触发信号的硬性约束）
            if pos.breakout_price > 0 and pos.breakout_date is not None:
                days_since_breakout = (date - pos.breakout_date).days
                if days_since_breakout <= 10 and current_price < pos.breakout_price * 0.95:
                    sig = SignalEvent.create(
                        symbol=symbol,
                        timestamp=date,
                        direction="sell",
                        strength=5,
                        reason=f"[Failed Breakout] Price reverted {((current_price/pos.breakout_price)-1)*100:.1f}% after breakout - exit all",
                        stop_loss=None,
                        cycle_stage="failed_breakout",
                        current_price=current_price,
                    )
                    signals.append(sig)
                    to_close.append(symbol)
                    continue



            # === Extension内分段卖出（PDF Page 10, 20, 42-43）===
            # PDF: 第1次Extension回落5%卖20%，第2次卖50%，第3次全卖
            gain_pct = (current_price / pos.entry_price - 1) * 100

            if pos.extension_count > 0 and pos.highest_extension_price > 0:
                # 参考价：取Extension最高价和上次减仓参考价中的较高者
                ref_price = max(pos.highest_extension_price, pos.last_sell_reference_price)
                # 回落5%触发卖出
                if ref_price > 0 and current_price < ref_price * 0.95:
                    # PDF Page 10, 20, 42-43:
                    # 第1次 Extension: sell ~20%
                    # 第2次 Extension: sell 50%
                    # 第3次 Extension: sell all
                    # Base n' Break 持仓：第1次 Extension 就应该卖 50%（更积极止盈）
                    is_base_n_break_position = (pos.current_stage == "base_n_break")
                    if is_base_n_break_position:
                        if pos.extension_count == 1:
                            trim_ratio = 0.50  # Base n' Break 第1次就卖50%
                        elif pos.extension_count == 2:
                            trim_ratio = 1.00  # 第2次全卖
                        else:
                            trim_ratio = 1.00  # 第3+次，全卖
                    else:
                        if pos.extension_count == 1:
                            trim_ratio = 0.20
                        elif pos.extension_count == 2:
                            trim_ratio = 0.50
                        else:
                            trim_ratio = 1.00  # 第3+次，全卖
                    shares_to_sell = int(pos.shares * trim_ratio) if pos.shares > 0 else 0
                    if shares_to_sell > 0:
                        if trim_ratio >= 1.0:
                            sig = SignalEvent.create(
                                symbol=symbol,
                                timestamp=date,
                                direction="sell",
                                strength=5,
                                reason=f"[Extension Sell #3] {ref_price:.2f}→{current_price:.2f} ({((current_price/ref_price)-1)*100:.1f}%) - sell all (+{gain_pct:.1f}%)",
                                stop_loss=None,
                                cycle_stage="extension_sell",
                                current_price=current_price,
                            )
                            signals.append(sig)
                            to_close.append(symbol)
                            continue
                        else:
                            sig = SignalEvent.create(
                                symbol=symbol,
                                timestamp=date,
                                direction="sell",
                                strength=4,
                                reason=f"[Extension Sell #{pos.extension_count}] {ref_price:.2f}→{current_price:.2f} ({((current_price/ref_price)-1)*100:.1f}%) - sell {trim_ratio*100:.0f}% (+{gain_pct:.1f}%)",
                                stop_loss=None,
                                shares=shares_to_sell,
                                cycle_stage="extension_sell",
                                current_price=current_price,
                            )
                            signals.append(sig)
                            pos.shares -= shares_to_sell
                            pos.last_sell_reference_price = current_price
                            if pos.shares <= 0:
                                to_close.append(symbol)
                                continue

            # === 时间止损：持有 >90天 且 涨幅 <10% → 平仓（极宽容兜底，Oliver Kell 用 EMA 趋势判断）===
            if pos.days_held > 90 and gain_pct < 10.0:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=2,  # 低优先级，不是主要出场信号
                    reason=f"[Long-term Time Stop] Held {pos.days_held} days, gain {gain_pct:.1f}% < 10%",
                    stop_loss=None,
                    cycle_stage="time_stop",
                    current_price=current_price,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # === 3x Trapped: price repeatedly near stop without progress ===
            # Oliver 的逻辑：如果价格反复贴近 EMA20 却没有进展，说明在消耗时间
            if current_price < ema20 and current_price >= ema20 * 0.97:
                if pos.days_held > 5:
                    pos.times_trapped += 1
                    if pos.times_trapped >= 3:
                        sig = SignalEvent.create(
                            symbol=symbol,
                            timestamp=date,
                            direction="sell",
                            strength=5,
                            reason=f"[3x Trapped] Price repeatedly near EMA20 without progress - exit",
                            stop_loss=None,
                            cycle_stage="3x_trapped",
                            current_price=current_price,
                        )
                        signals.append(sig)
                        to_close.append(symbol)
                        continue

        for symbol in to_close:
            del self.positions[symbol]
            if symbol in self.scale_in.positions:
                del self.scale_in.positions[symbol]

        for sig in signals:
            self._attach_weinstein_stage(sig, date)

        return signals

    def _find_buy_signals(
        self,
        date: datetime,
        market_state: MarketState,
        max_position_pct: float,
        recent_wedge_pop_stocks: set[str] | None = None,
    ) -> list[SignalEvent]:
        """扫描个股找买入信号"""
        signals = []
        require_wedge_first = self.cfg.get("require_wedge_pop_first", False)

        # 获取 QQQ 数据用于 RS Line 检查
        qqq_df = self._get_index_data()

        for symbol, df in self.market_data.items():
            if symbol in ("SPY", "^VIX", "QQQ", "ASHR", "EWT"):
                continue

            df_to_date = self._slice_to_date(df, date)
            if len(df_to_date) < 25:
                continue

            # === 周K趋势过滤：日K信号需要周K确认 ===
            if not self.cycle_detector.is_weekly_uptrend(df_to_date):
                continue

            # === 先判断阶段，再决定用哪些过滤 ===
            stage = self.cycle_detector.classify(df_to_date)

            # === Exhaustion Extension：此阶段不开新仓 ===
            if stage == CycleStage.EXHAUSTION_EXTENSION:
                continue

            # === EMA 多头排列过滤 ===
            # 有 50+ 天数据时：Price > EMA10 > EMA20 且两者都在上升
            # 数据不足 50 天时使用宽松版本：Price > EMA10 > EMA20 且上升
            # Wedge Pop 例外：EMA10/20可能在缠绕，Wedge Pop是最佳买点不需要完美排列
            if stage != CycleStage.WEDGE_POP:
                if len(df_to_date) >= 50:
                    if not self.cycle_detector.is_perfect_stack(df_to_date):
                        continue
                elif len(df_to_date) >= 20:
                    if not self.cycle_detector.is_bullish_alignment(df_to_date):
                        continue

            # === 价格门槛过滤（PDF Page 30: "I do not trade stocks under $10"）===
            # 使用 _get_row_for_date 避免 iloc[-1] 返回次日 05:00 bar 的问题
            row = self._get_row_for_date(df, date)
            if row is None:
                continue
            current_price = float(row["close"])
            if current_price < 10:
                continue

            # === RS Line 过滤（PDF pages 15-17, 28）===
            # "Buy the strongest stocks on a relative basis"
            # Require stock's RS Line is leading (above its 20dma and making higher highs)
            if not self.cycle_detector.is_rs_leading(df_to_date, qqq_df):
                continue

            signal = self._check_entry(symbol, df_to_date, date, market_state, qqq_df)
            if signal:
                signals.append(signal)

        # 按信号强度排序
        signals.sort(key=lambda s: s.data["strength"], reverse=True)

        # 所有信号都输出，不设上限
        return signals

    def _find_short_signals(
        self,
        date: datetime,
        market_state: MarketState,
    ) -> list[SignalEvent]:
        """扫描个股找做空信号

        做空信号类型：
            1. Wedge Drop Short：价格跌破 EMA + EMA 向下拐头（下降趋势确认）
            2. Exhaustion Short：价格极度远离 EMA + Gap Up（顶部衰竭警告）

        做空逻辑：
            - Wedge Drop Short：市场不能是 POOR 状态（指数 Wedge Drop 时不开新空）
            - Exhaustion Short：在指数顶部区域时胜率更高
            - 价格低于 $10 不做空
        """
        signals = []

        for symbol, df in self.market_data.items():
            # 跳过指数和 VIX
            if symbol in ("SPY", "^VIX", "QQQ", "ASHR", "EWT"):
                continue

            df_to_date = self._slice_to_date(df, date)
            if len(df_to_date) < 25:
                continue

            # 获取当前日期的正确行（避免 iloc[-1] 问题）
            row = self._get_row_for_date(df, date)
            if row is None:
                continue
            current_price = float(row["close"])

            # === 检查 Wedge Drop Short ===
            stage = self.cycle_detector.classify(df_to_date)

            if stage == CycleStage.WEDGE_DROP:
                # 计算 EMA 用于止损
                ema10 = float(df_to_date["close"].ewm(span=10).mean().loc[row.name]) if row.name in df_to_date["close"].ewm(span=10).mean().index else float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
                ema20 = float(df_to_date["close"].ewm(span=20).mean().loc[row.name]) if row.name in df_to_date["close"].ewm(span=20).mean().index else float(df_to_date["close"].ewm(span=20).mean().iloc[-1])

                # 做空止损：EMA20 × 1.02（允许2%穿透，空头止损在 EMA20 上方 2%）
                stop = round(ema20 * 1.02, 2)

                # 计算偏离EMA幅度
                dist_to_ema10 = (current_price - ema10) / ema10 * 100
                dist_to_ema20 = (current_price - ema20) / ema20 * 100
                daily_dist_pct = min(dist_to_ema10, dist_to_ema20)

                rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio = self._compute_signal_metrics(df_to_date)
                metric_note = (
                    self._format_rs_short_note(rs_value_10d)
                    + self._format_rs_note(rs_value_20d)
                    + self._format_rs_long_note(rs_value_10w)
                    + self._format_vol_note(vol_ratio)
                    + self._format_oneil_rs_note(*self._get_oneil_rs(symbol))
                )

                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="short",
                    strength=5,
                    reason=(
                        f"[Wedge Drop Short] Entry{metric_note} | "
                        f"[EMA] 10={ema10:.1f}, 20={ema20:.1f} | "
                        f"[偏离EMA] {daily_dist_pct:.1f}% | "
                        f"[Price] ${current_price:.2f} | "
                        f"[Stage] wedge_drop"
                    ),
                    stop_loss=stop,
                    position_dollar=5000.0,
                    cycle_stage="wedge_drop_short",
                    current_price=current_price,
                )
                sig.data["rs_value_10d"] = rs_value_10d
                sig.data["rs_value"] = rs_value_20d
                sig.data["rs_value_10w"] = rs_value_10w
                sig.data["volume_ratio"] = vol_ratio
                sig.data["rs_rating"] = self._get_oneil_rs(symbol)[0]
                sig.data["rs_ratio"] = self._get_oneil_rs(symbol)[1]
                signals.append(sig)
                continue

            # === 检查 Exhaustion Short ===
            if stage == CycleStage.EXHAUSTION_EXTENSION:
                today_high = float(row["high"])
                prev_row = self._get_prev_day_row(df)
                yesterday_close = float(prev_row["close"]) if prev_row is not None else current_price

                # Gap Up 检查：当天开盘明显高于昨天收盘
                gap_up_pct = (current_price - yesterday_close) / yesterday_close if yesterday_close > 0 else 0

                # 只有出现 Gap Up + 远离 EMA 才是有效 Exhaustion Short
                if gap_up_pct >= 0.03:
                    ema10 = float(df_to_date["close"].ewm(span=10).mean().loc[row.name]) if row.name in df_to_date["close"].ewm(span=10).mean().index else float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
                    ema20 = float(df_to_date["close"].ewm(span=20).mean().loc[row.name]) if row.name in df_to_date["close"].ewm(span=20).mean().index else float(df_to_date["close"].ewm(span=20).mean().iloc[-1])

                    # 做空止损：当日高点 × 1.02
                    stop = round(today_high * 1.02, 2)

                    # 计算偏离EMA幅度
                    dist_to_ema10 = (current_price - ema10) / ema10 * 100
                    dist_to_ema20 = (current_price - ema20) / ema20 * 100
                    daily_dist_pct = max(dist_to_ema10, dist_to_ema20)

                    rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio = self._compute_signal_metrics(df_to_date)
                    metric_note = (
                    self._format_rs_short_note(rs_value_10d)
                    + self._format_rs_note(rs_value_20d)
                    + self._format_rs_long_note(rs_value_10w)
                    + self._format_vol_note(vol_ratio)
                    + self._format_oneil_rs_note(*self._get_oneil_rs(symbol))
                )

                    sig = SignalEvent.create(
                        symbol=symbol,
                        timestamp=date,
                        direction="short",
                        strength=4,
                        reason=(
                            f"[Exhaustion Short] Entry{metric_note} | "
                            f"[EMA] 10={ema10:.1f}, 20={ema20:.1f} | "
                            f"[偏离EMA] {daily_dist_pct:.1f}% | "
                            f"[Gap Up] {gap_up_pct*100:.1f}% | "
                            f"[Stage] exhaustion_extension"
                        ),
                        stop_loss=stop,
                        position_dollar=5000.0,
                        cycle_stage="exhaustion_short",
                        current_price=current_price,
                    )
                    sig.data["rs_value_10d"] = rs_value_10d
                    sig.data["rs_value"] = rs_value_20d
                    sig.data["rs_value_10w"] = rs_value_10w
                    sig.data["volume_ratio"] = vol_ratio
                    sig.data["rs_rating"] = self._get_oneil_rs(symbol)[0]
                    sig.data["rs_ratio"] = self._get_oneil_rs(symbol)[1]
                    signals.append(sig)

        # 按信号强度排序
        signals.sort(key=lambda s: s.data["strength"], reverse=True)

        return signals

    def _check_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        market_state: MarketState,
        qqq_df: pd.DataFrame | None = None,
    ) -> SignalEvent | None:
        """
        检查个股是否满足买入条件。

        买入信号（按原文优先级）：
            1. Wedge Pop（最佳买点）
            2. EMA Crossback（回踩加仓）
            3. Base n' Break（趋势延续）
        """
        close = float(df["close"].iloc[-1])
        ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
        ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])

        # 识别当前阶段
        stage = self.cycle_detector.classify(df)

        # Wedge Pop
        if stage == CycleStage.WEDGE_POP:
            return self._handle_wedge_pop(symbol, df, date, close, ema10, ema20, stage, qqq_df)

        # EMA Crossback (Page 11, 20): "first pullback to 10/20 EMA — low risk buy opportunity"
        if stage == CycleStage.EMA_CROSSBACK:
            return self._handle_ema_crossback(symbol, df, date, close, ema10, ema20, stage, qqq_df)

        # Base n' Break: 独立买入信号（第3+次回踩后的突破）
        # 原文：Can add small during consolidation, full size at breakout
        # 与EMA Crossback的区别：EMA Crossback是回踩确认买入，Base n' Break是突破盘整买入
        if stage == CycleStage.BASE_N_BREAK:
            return self._handle_base_n_break(symbol, df, date, close, stage)

        # === Variant Patterns：平行入场信号，不依赖 UNKNOWN ===
        # PDF 展示的 Bull Flag / Bull Pennant / VCP 是独立入场形态
        # 不在 EXHAUSTION_EXTENSION / WEDGE_DROP / REVERSAL_EXTENSION 阶段时才考虑
        if stage not in (CycleStage.EXHAUSTION_EXTENSION, CycleStage.WEDGE_DROP, CycleStage.REVERSAL_EXTENSION):
            if market_state not in (MarketState.POOR, MarketState.HOSTILE):
                # 持仓中仍显示 Variant Patterns 信号（仅供参考）
                # 已移除: if symbol not in self.positions:
                if True:
                    if self.cycle_detector.is_vcp(df):
                        return self._handle_variant_pattern(symbol, df, date, close, "VCP")
                    if self.cycle_detector.is_bull_flag(df):
                        return self._handle_variant_pattern(symbol, df, date, close, "Bull Flag")
                    if self.cycle_detector.is_bull_pennant(df):
                        return self._handle_variant_pattern(symbol, df, date, close, "Bull Pennant")

        # === Base n' Break = TAKE PROFITS (Page 11, 14, 20, 23) ===
        # "Second extension from the 10 EMA is good place to take profits"
        # "Third extension = late in intermediate-term trend"
        # 持仓中仍显示 Base n' Break 信号（仅供参考，不重复建仓）
        if stage == CycleStage.BASE_N_BREAK:
            # 已移除: if symbol not in self.positions: return None
            pass

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
        qqq_df: pd.DataFrame | None = None,
    ) -> SignalEvent:
        """
        Wedge Pop 入场。

        原文：
            - Initial position: 25-35% Top Idea of account
            - Stop: Below breakout day closing low
            - Best risk/reward entry in the entire cycle
        """
        # === 持仓中仍显示信号（仅供参考，不重复建仓） ===
        already_in_position = symbol in self.positions

        # === 获取楔形信息 ===
        wedge_info = self.cycle_detector.get_wedge_info(df)
        if wedge_info is None:
            return None  # 没有有效楔形

        # === RS Line 检查：RS Line 开始领先市场 ===
        # rs_leading 仅做内部判断使用；对外输出 RS 数值与量比
        rs_leading = False
        if qqq_df is not None and len(qqq_df) >= 20:
            rs_leading = self.cycle_detector.is_rs_leading(df, qqq_df)

        # 计算 RS 数值 + 量比（用于 reason 与 SignalEvent.data）
        rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio = self._compute_signal_metrics(df)
        metric_note = (
                    self._format_rs_short_note(rs_value_10d)
                    + self._format_rs_note(rs_value_20d)
                    + self._format_rs_long_note(rs_value_10w)
                    + self._format_vol_note(vol_ratio)
                    + self._format_oneil_rs_note(*self._get_oneil_rs(symbol))
                )

        # 突破价位 = 楔形上轨（用于 Failed Breakout 检测）
        breakout_price = wedge_info["wedge_upper"]

        # === 止损锚点 = 突破日的收盘价（PDF Page 17）===
        # PDF Page 17: "Stop: Below breakout day closing low"
        # 用当天收盘价，不是绝对低点！"closing low" = 收盘价，不是最低价
        today_close = float(df["close"].iloc[-1])
        breakout_low = today_close if wedge_info.get("is_breakout") else today_close

        stop = round(breakout_low * 0.98, 2)  # 2% buffer below breakout day close

        # === 持仓中仍显示信号（仅供参考，不重复建仓） ===
        already_in_position = symbol in self.positions

        if not already_in_position:
            # 记录持仓
            position = OKPosition(
                symbol=symbol,
                entry_price=close,
                entry_date=date,
                highest_price=close,
                shares=0,
                batch_state=BatchState.BATCH1_OPEN,
                current_stage="wedge_pop",
                breakout_price=breakout_price,
                breakout_date=date,
                entry_stop_price=breakout_low,
            )
            self.positions[symbol] = position

            # 触发 scale_in
            self.scale_in.on_wedge_pop(symbol, close, stop, date)

        reason = (
            f"[Wedge Pop] Best entry{metric_note} | "
            f"[EMA] 10={ema10:.1f}, 20={ema20:.1f} | "
            f"[Stage] {stage.value}"
        )

        event = SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=5,
            reason=reason,
            stop_loss=stop,
            position_dollar=5000.0,
            cycle_stage="wedge_pop",
            current_price=close,
        )
        event.data["rs_value_10d"] = rs_value_10d
        event.data["rs_value"] = rs_value_20d
        event.data["rs_value_10w"] = rs_value_10w
        event.data["volume_ratio"] = vol_ratio
        event.data["rs_rating"] = self._get_oneil_rs(symbol)[0]
        event.data["rs_ratio"] = self._get_oneil_rs(symbol)[1]
        return event

    def _handle_ema_crossback(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        ema10: float,
        ema20: float,
        stage: CycleStage,
        qqq_df: pd.DataFrame | None = None,
    ) -> SignalEvent | None:
        """
        EMA Crossback 入场/加仓。

        原文：
            - EMA Crossback 是独立入场信号
            - 不检查是否已有仓位，不检查重复，有信号就买
        """
        today_low = float(df["low"].iloc[-1])
        prev_row = self._get_prev_day_row(df)
        yesterday_low = float(prev_row["low"])

        # 原文（Page 20）：Stop for EMA Crossback is "below pullback day low"
        # 回踩日是昨天，所以止损在昨天最低价
        stop = round(yesterday_low * 0.99, 2)  # 1% buffer below pullback day low

        # === 持仓中仍显示信号（仅供参考） ===
        # 已有持仓时，只返回信号但不重复建仓
        already_in_position = symbol in self.positions

        if not already_in_position:
            position = OKPosition(
                symbol=symbol,
                entry_price=close,
                entry_date=date,
                highest_price=close,
                shares=0,
                batch_state=BatchState.BATCH1_OPEN,
                current_stage="ema_crossback",
                entry_stop_price=yesterday_low,  # PDF Page 20: pullback day low
            )
            self.positions[symbol] = position
            self.scale_in.on_wedge_pop(symbol, close, stop, date)

        rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio = self._compute_signal_metrics(df)
        metric_note = (
                    self._format_rs_short_note(rs_value_10d)
                    + self._format_rs_note(rs_value_20d)
                    + self._format_rs_long_note(rs_value_10w)
                    + self._format_vol_note(vol_ratio)
                    + self._format_oneil_rs_note(*self._get_oneil_rs(symbol))
                )

        reason = (
            f"[EMA Crossback] Entry{metric_note} | "
            f"[EMA] 10={ema10:.1f}, 20={ema20:.1f} | "
            f"[Stage] {stage.value}"
        )

        event = SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=4,
            reason=reason,
            stop_loss=stop,
            position_dollar=5000.0,
            cycle_stage="ema_crossback",
            current_price=close,
        )
        event.data["rs_value_10d"] = rs_value_10d
        event.data["rs_value"] = rs_value_20d
        event.data["rs_value_10w"] = rs_value_10w
        event.data["volume_ratio"] = vol_ratio
        event.data["rs_rating"] = self._get_oneil_rs(symbol)[0]
        event.data["rs_ratio"] = self._get_oneil_rs(symbol)[1]
        return event

    def _handle_base_n_break(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        stage: CycleStage,
    ) -> SignalEvent | None:
        """
        Base n' Break 入场信号（独立买入，不依赖是否有持仓）。

        原文：
            - Can add small during consolidation, full size at breakout
            - This pattern can repeat multiple times

        每笔买入金额2000美元（Wedge Pop/EMA Crossback为5000美元）
        """
        # 盘整区间
        lookback = self.cfg.get("base_lookback", 20)
        consolidation_high = float(df["high"].iloc[-lookback:].max())
        base_low = float(df["low"].iloc[-lookback:].min())

        # PDF Page 20: "stop below the moving averages" = below EMA10
        ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
        entry_stop = round(ema10 * 0.97, 2)  # 3% below EMA10
        stop = round(ema10 * 0.97, 2)

        # === 持仓中仍显示信号（仅供参考，不重复建仓） ===
        already_in_position = symbol in self.positions

        if not already_in_position:
            # 记录持仓（和 Wedge Pop/EMA Crossback 一样）
            position = OKPosition(
                symbol=symbol,
                entry_price=close,
                entry_date=date,
                highest_price=close,
                shares=0,
                batch_state=BatchState.BATCH1_OPEN,
                current_stage="base_n_break",
                breakout_price=consolidation_high,
                breakout_date=date,
                entry_stop_price=entry_stop,  # PDF: below the moving averages
            )
            self.positions[symbol] = position
            self.scale_in.on_wedge_pop(symbol, close, stop, date)

        rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio = self._compute_signal_metrics(df)
        metric_note = (
                    self._format_rs_short_note(rs_value_10d)
                    + self._format_rs_note(rs_value_20d)
                    + self._format_rs_long_note(rs_value_10w)
                    + self._format_vol_note(vol_ratio)
                    + self._format_oneil_rs_note(*self._get_oneil_rs(symbol))
                )

        reason = (
            f"[Base n' Break] Entry{metric_note} | "
            f"[Base Low] ${base_low:.2f} | "
            f"[Stage] {stage.value}"
        )

        # Base n' Break 独立买入，每笔2000美元
        event = SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=3,
            reason=reason,
            stop_loss=stop,
            position_dollar=2000.0,
            cycle_stage="base_n_break",
            current_price=close,
        )
        event.data["rs_value_10d"] = rs_value_10d
        event.data["rs_value"] = rs_value_20d
        event.data["rs_value_10w"] = rs_value_10w
        event.data["volume_ratio"] = vol_ratio
        event.data["rs_rating"] = self._get_oneil_rs(symbol)[0]
        event.data["rs_ratio"] = self._get_oneil_rs(symbol)[1]
        return event

    def _handle_variant_pattern(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        pattern_name: str,
    ) -> SignalEvent | None:
        """
        Variant Patterns（VCP / Bull Flag / Bull Pennant）入场。

        这些都是 Base n' Break 的变体，处理方式类似。
        """
        pos = self.positions.get(symbol)
        if pos and pos.batch_state == BatchState.BATCH2_OPEN:
            return None  # 30% 已满，不再加
        # 持仓中仍显示信号（仅供参考，不重复建仓）
        # 已移除: if symbol in self.positions: return None

        # 盘整区间
        lookback = 20
        consolidation_high = float(df["high"].iloc[-lookback:].max())
        base_low = float(df["low"].iloc[-lookback:].min())
        stop = round(base_low * (1 - 0.02), 2)

        if pos is None:
            position = OKPosition(
                symbol=symbol,
                entry_price=close,
                entry_date=date,
                highest_price=close,
                shares=0,
                batch_state=BatchState.BATCH1_OPEN,
                current_stage=pattern_name.lower().replace(" ", "_"),
                breakout_price=consolidation_high,
                breakout_date=date,
            )
            self.positions[symbol] = position

        rs_value_10d, rs_value_20d, rs_value_10w, vol_ratio = self._compute_signal_metrics(df)
        metric_note = (
                    self._format_rs_short_note(rs_value_10d)
                    + self._format_rs_note(rs_value_20d)
                    + self._format_rs_long_note(rs_value_10w)
                    + self._format_vol_note(vol_ratio)
                    + self._format_oneil_rs_note(*self._get_oneil_rs(symbol))
                )

        reason = (
            f"[{pattern_name}] Pattern breakout{metric_note} | "
            f"[Base Low] ${base_low:.2f} | "
            f"[Variant]"
        )

        event = SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=2,  # 变体形态优先级略低
            reason=reason,
            stop_loss=stop,
            cycle_stage=pattern_name.lower().replace(" ", "_"),
            current_price=close,
        )
        event.data["rs_value_10d"] = rs_value_10d
        event.data["rs_value"] = rs_value_20d
        event.data["rs_value_10w"] = rs_value_10w
        event.data["volume_ratio"] = vol_ratio
        event.data["rs_rating"] = self._get_oneil_rs(symbol)[0]
        event.data["rs_ratio"] = self._get_oneil_rs(symbol)[1]
        return event

    def _slice_to_date(self, df: pd.DataFrame, date: datetime) -> pd.DataFrame:
        """切片到指定日期"""
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        idx = df.index
        if idx.tzinfo is None:
            idx = idx.tz_localize("UTC")
            df = df.copy()
            df.index = idx
        return df[df.index < date + pd.Timedelta(days=1)]

    def _check_batch2_triggers(self, date: datetime) -> list[SignalEvent]:
        """
        检查 Batch 2 加仓信号。

        原文：
            - Batch 1 profitable, follow-through confirmation next day
            - Simultaneously raise stop to "follow-through day" low
            - Total account risk still ~20-30bps
        """
        signals = []

        for symbol, pos in list(self.positions.items()):
            # Safety: skip if position was closed by exit earlier in same loop
            if symbol not in self.positions:
                continue
            if pos.batch_state != BatchState.BATCH1_OPEN:
                continue  # 只对 Batch 1 持仓检查

            df = self.market_data.get(symbol)
            if df is None or df.empty:
                continue

            df_to_date = self._slice_to_date(df, date)
            if len(df_to_date) < 2:
                continue

            # 使用 _get_row_for_date 获取正确的当日收盘行
            row = self._get_row_for_date(df, date)
            if row is None:
                continue
            current_price = float(row["close"])
            # 找到前一个交易日的价格
            df_before = df_to_date[df_to_date.index < row.name]
            if len(df_before) < 1:
                continue
            prev_price = float(df_before["close"].iloc[-1])

            # Batch 1 必须已盈利
            if current_price <= pos.entry_price:
                continue

            # 今天价格必须上涨（follow-through confirmation）
            if current_price <= prev_price:
                continue

            # 触发 Batch 2
            # 止损上移至今天的最低价（原文：raise stop to follow-through day low）
            new_stop = round(current_price * 0.98, 2)

            sig = SignalEvent.create(
                symbol=symbol,
                timestamp=date,
                direction="buy",
                strength=4,
                reason=f"[Batch 2] Follow-through confirmed (+{(current_price/pos.entry_price-1)*100:.1f}%), stop raised to ${new_stop:.2f}",
                stop_loss=new_stop,
                cycle_stage="batch2",
                current_price=current_price,
            )
            signals.append(sig)

            # 更新持仓状态
            pos.batch_state = BatchState.BATCH2_OPEN
            # 同时更新 scale_in
            self.scale_in.on_follow_through(
                symbol,
                follow_through_low=float(row["low"]) if "low" in row else float(df_to_date["low"].iloc[-1]),
                entry_date=date,
                batch2_entry_price=current_price,
            )

        return signals

    def _detect_and_update_ignite_bar(self, pos: OKPosition, df: pd.DataFrame) -> None:
        """
        检测 Ignite Bar 并更新持仓的 ignite_bar_low。

        原文（PDF pages 25, 32-33）：
            "When we see an Ignite Bar low, we want to adjust our stops
             to the low of that bar."

        逻辑：
            1. 检测今天的数据是否有 Ignite Bar
            2. 如果检测到，且其 low 高于当前的 ignite_bar_low，则更新
            3. ignite_bar_low 只会上调，不会下调（我们只 raise stops）

        Ignite Bar 定义：
            - 今日是看涨蜡烛线（close > open）
            - 今日区间幅度 >= 3%（(high - low) / low > 0.03）
            - 成交量 >= 1.5x 20日均量
        """
        if df is None or len(df) < 21:
            return

        ignite_low = self.cycle_detector.detect_ignite_bar(df)

        # 只有当 ignite_low 高于当前记录的才更新（只 raise，不 lower）
        # 使用 getattr 处理旧版本加载的 Position 对象（可能没有 ignite_bar_low 属性）
        current_ignite_low = getattr(pos, 'ignite_bar_low', 0.0)
        if ignite_low > current_ignite_low:
            pos.ignite_bar_low = ignite_low

    def _is_gap_up_exhaustion(self, df: pd.DataFrame, ema10: float) -> bool:
        """
        Gap up exhaustion 检测（PDF page 26）。

        条件：
            - 价格从 EMA 大幅偏离（extended > 5%）
            - 跳空高开 3%+
            - 当前价格创 extension 期间新高

        Returns:
            True if gap up exhaustion detected
        """
        if df is None or len(df) < 2:
            return False

        current = float(df["close"].iloc[-1])
        prev_row = self._get_prev_day_row(df)
        yesterday_close = float(prev_row["close"])

        gap_up_pct = (current - yesterday_close) / yesterday_close
        is_extended = current > ema10 * 1.05

        return gap_up_pct >= 0.03 and is_extended

    def get_open_positions(self) -> dict[str, OKPosition]:
        return dict(self.positions)