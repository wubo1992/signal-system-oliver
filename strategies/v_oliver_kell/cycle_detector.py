"""
strategies/v_oliver_kell/cycle_detector.py

Cycle of Price Action 六阶段识别（原文 Section 2）：

    ① Reversal Extension  — 底部恐慌，不买
    ② Wedge Pop         — 最佳买点（买入）
    ③ EMA Crossback     — 回踩加仓（买入）
    ④ Base n' Break     — 趋势延续（买入/加仓）
    ⑤ Exhaustion Ext    — 顶部警告（不减仓，只观察不开新仓）
    ⑥ Wedge Drop        — 下降确认（卖出）
"""

from enum import Enum
import numpy as np
import pandas as pd


class CycleStage(Enum):
    REVERSAL_EXTENSION = "reversal_extension"
    WEDGE_POP = "wedge_pop"
    # EMA Crossback is NOT a separate stage (per PDF page 11):
    # "This is not really a step in the Cycle of Price Action, this is simply
    # a pullback to the EMAs... It may be in the form of a one to two day
    # pullback and can be used as an opportunity to add to positions."
    # We keep it as a stage for classification but it should be treated as
    # a pullback/add signal, not a primary entry stage.
    EMA_CROSSBACK = "ema_crossback"
    BASE_N_BREAK = "base_n_break"  # Second/third extension = TAKE PROFITS, not buy
    EXHAUSTION_EXTENSION = "exhaustion_extension"
    WEDGE_DROP = "wedge_drop"
    UNKNOWN = "unknown"


class CycleDetector:
    """
    识别价格处于 Cycle of Price Action 的哪个阶段。

    核心逻辑：
        1. 计算 10EMA、20EMA（原文：10-day EMA / 20-day EMA）
        2. 判断 EMA 方向和斜率
        3. 判断价格与 EMA 的关系
        4. 综合判断当前阶段
    """

    def __init__(self, wedge_lookback: int = 20, base_lookback: int = 20):
        self.wedge_lookback = wedge_lookback
        self.base_lookback = base_lookback

    def classify(self, df: pd.DataFrame) -> CycleStage:
        """
        判断当前所处阶段。

        参数：
            df: 含 close, EMA10, EMA20, SMA50, SMA200, volume 的 DataFrame

        返回：
            CycleStage 枚举值
        """
        if len(df) < 25:
            return CycleStage.UNKNOWN

        current = float(df["close"].iloc[-1])
        ema10_series = df["close"].ewm(span=10).mean()
        ema20_series = df["close"].ewm(span=20).mean()
        sma50_series = df["close"].rolling(50).mean()
        sma200_series = df["close"].rolling(200).mean()

        ema10 = float(ema10_series.iloc[-1])
        ema20 = float(ema20_series.iloc[-1])
        sma50 = float(sma50_series.iloc[-1])
        sma200 = float(sma200_series.iloc[-1])

        # 前一天的值
        ema10_prev = float(ema10_series.iloc[-2])
        ema20_prev = float(ema20_series.iloc[-2])
        sma50_prev = float(sma50_series.iloc[-2])
        sma200_prev = float(sma200_series.iloc[-2])

        # EMA 斜率
        ema10_slope = ema10 - ema10_prev
        ema20_slope = ema20 - ema20_prev

        # 1. Wedge Pop 检测（突破 wedge 上轨 + 站上 EMA）
        if self._is_wedge_pop(df, ema10, ema20, ema10_prev, ema20_prev):
            return CycleStage.WEDGE_POP

        # 2. 计算回踩次数（决定用 EMA Crossback 还是 Base n' Break）
        pullback_count = self.count_pullbacks_since_wedge_pop(df)

        # 3. EMA Crossback 检测（回踩 EMA）
        #    PDF Page 11, 20: "first pullback to the 10/20 EMA"
        #    pullback_count >= 1 表示有回踩发生过，可以触发 EMA Crossback
        #    注意：EMA Crossback 优先于 Exhaustion Extension，
        #    因为回踩后的第二天延伸不一定是衰竭（可能是正常反弹）
        if pullback_count >= 1:
            if self._is_ema_crossback(df, ema10, ema20, ema10_prev, ema20_prev):
                return CycleStage.EMA_CROSSBACK

        # 4. Exhaustion Extension 检测（价格远离 EMA）
        if self._is_exhaustion_extension(df):
            return CycleStage.EXHAUSTION_EXTENSION

        # 5. Base n' Break 检测（盘整后突破，第3+次回踩或突破）
        if self._is_base_n_break(df):
            return CycleStage.BASE_N_BREAK

        # 6. Wedge Drop 检测（跌破 EMA）
        if self._is_wedge_drop(df, ema10, ema20, ema10_prev, ema20_prev):
            return CycleStage.WEDGE_DROP

        # 7. Reversal Extension 检测（底部信号）
        if self._is_reversal_extension(df):
            return CycleStage.REVERSAL_EXTENSION

        return CycleStage.UNKNOWN

    def _is_exhaustion_extension(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification（Page 11, 26）：
        - Price far from 10/20 EMA (daily AND weekly both exceed 10%)
        - First retest of MAs following Wedge Pop
        - Volume shows climax run
        - CRITICAL (Page 26): "When a stock gets extended into its trend,
          gets extended from the 10-Day EMA, and has a large gap up,
          this can often be a time to sell or at least partially sell"
        """
        if len(df) < 25:
            return False

        current = float(df["close"].iloc[-1])
        ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])
        ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
        prev_row = self._get_prev_day_row(df)
        yesterday_close = float(prev_row["close"])

        # === Gap Up Exhaustion (Page 26): stock extended + gap up = sell signal ===
        # 只在价格位于 EMA 上方（上涨趋势延伸）时才算 Exhaustion；
        # 远离均线下方 + 跳空属于超卖反弹 (Dead Cat Bounce)，不算顶部耗尽。
        if current > ema10 and current > ema20:
            daily_dist = max(
                (current - ema10) / ema10,
                (current - ema20) / ema20,
            )
        else:
            daily_dist = 0.0
        if daily_dist >= 0.10:
            # Check for gap up: today opens significantly above yesterday's close
            gap_up_pct = (current - yesterday_close) / yesterday_close
            if gap_up_pct >= 0.03:  # 3%+ gap up while extended
                return True

        # 日K：价格远离 EMA10/20 超过 10%（仅向上偏离）
        if daily_dist < 0.10:
            return False

        # 周K：同样检查，超过 10% 才触发
        weekly = self.get_weekly_ema(df)
        if weekly.empty or len(weekly) < 5:
            return False
        w_close = float(weekly["close"].iloc[-1])
        w_ema10 = float(weekly["EMA10"].iloc[-1])
        w_ema20 = float(weekly["EMA20"].iloc[-1])
        weekly_dist = max(
            abs(w_close - w_ema10) / w_ema10,
            abs(w_close - w_ema20) / w_ema20,
        )
        if weekly_dist < 0.10:
            return False

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

    def _verify_wedge_pop_prerequisite(self, df: pd.DataFrame, ema10: float, ema20: float) -> bool:
        """
        Verify the 3-step Wedge Pop prerequisite per PDF pages 13, 33, 60:

        Step 1 - EMA Resistance: Price rallies to the 20 EMA and gets REJECTED
                 (failed to break through). Price reached near EMA but couldn't
                 break above it.

        Step 2 - Basing Under EMA: Price then bases/consolidates UNDER the EMA
                 (not above it). EMAs are tightening (confirmed separately by
                 _are_emals_tightening).

        Step 3 - Pop Through: Price breaks above the EMA with volume (checked
                 by _is_wedge_pop caller).

        Returns True if the prior resistance + basing-under-EMA sequence is met.
        """
        if len(df) < 20:
            return False

        ema10_series = df["close"].ewm(span=10).mean()
        ema20_series = df["close"].ewm(span=20).mean()

        # Look back 5-20 days for the rally and rejection
        lookback = min(20, len(df) - 5)
        recent = df.iloc[-lookback:]

        current = float(df["close"].iloc[-1])

        # === Step 1: Find most recent rally that reached near EMA and was rejected ===
        # Scan from most recent going back: find first time price got within 2% of EMA20
        # Then verify it failed to break through (price closed at or below EMA at that rally)
        rally_found = False
        for i in range(len(recent) - 3):
            idx = -(i + 1)  # Go backwards from most recent
            price = float(df["close"].iloc[idx])
            ema20_at_time = float(ema20_series.iloc[idx])
            ema10_at_time = float(ema10_series.iloc[idx])

            # Price reached near EMA20 (within 2%)
            if price >= ema20_at_time * 0.98:
                # Check if price actually BROKE THROUGH EMA or was rejected
                # If price closed at or below EMA, it was rejected (resisted)
                # Also check: was this a rally that came from below?
                if price <= ema20_at_time * 1.01:  # Closed near or below EMA = rejection
                    rally_found = True

                    # Verify this rally came from below (not already above EMA)
                    if idx + 1 >= len(df):
                        continue
                    prev_price = float(df["close"].iloc[idx + 1])
                    prev_ema20 = float(ema20_series.iloc[idx + 1])
                    if prev_price > prev_ema20:
                        # Was already above EMA, not a rally to EMA
                        continue

                    rally_found = True
                    break

        if not rally_found:
            return False

        # === Step 2: After rally/rejection, price must BASE UNDER EMA ===
        # Find the rally index, then check all bars after it (up to today)
        # All these bars should have price BELOW or AT the EMA (basing under)
        # At least 2-3 basing days required after rejection
        rally_idx = len(df) - lookback + i

        # Check at least 2 days of basing after rally
        basing_days = 0
        for j in range(rally_idx, len(df) - 1):  # Up to yesterday
            price_j = float(df["close"].iloc[j])
            ema20_j = float(ema20_series.iloc[j])
            # Price should be at or near EMA (within 3% = basing under)
            if price_j <= ema20_j * 1.03:
                basing_days += 1

        # Need at least 2 basing days after the rally rejection
        if basing_days < 2:
            return False

        # === Current price must still be below EMA (not already above) ===
        # If already above EMA, the basing phase has completed
        if current > ema20 * 1.02:
            return False

        return True

    def _get_prev_day_row(self, df: pd.DataFrame) -> pd.Series | None:
        """
        获取前一天的正确bar。

        yfinance对美股每天返回两个bar（05:00和14:30 UTC），
        其中14:30的bar才是当天收盘，05:00是次日盘前。
        直接用iloc[-2]可能取到当天盘前bar而非前一天收盘bar。

        修复：找到当前日期前一个日历日的最后一个bar。
        """
        if len(df) < 2:
            return None

        current_idx = df.index[-1]
        # 找到前一个日历日
        prev_day = current_idx.normalize() - pd.Timedelta(days=1)

        # 在df中找到属于prev_day日期的最后一行
        mask = df.index.normalize() == prev_day
        matches = df[mask]
        if len(matches) > 0:
            return matches.iloc[-1]

        # 如果没找到，fallback到iloc[-2]（适用于单bar股票）
        return df.iloc[-2]

    def _is_wedge_pop(self, df: pd.DataFrame, ema10: float, ema20: float,
                       ema10_prev: float, ema20_prev: float) -> bool:
        """
        原文 Identification（Pages 13, 32）：
        - Price bounces from low, consolidates in contracting Wedge
        - CRITICAL prerequisite: 10/20 EMA must be TIGHTENING before the pop (page 32)
        - Price breaks Wedge upper bound AND crosses above 10/20 EMA
        - Volume expansion (accumulation confirmation)

        Stop: Below the breakout day LOW (page 13, 20, 25)
        """
        if len(df) < self.wedge_lookback + 5:
            return False

        lookback = self.wedge_lookback
        recent = df.iloc[-lookback:]

        current = float(df["close"].iloc[-1])

        # === CRITICAL: Check EMA tightening prerequisite (Page 32) ===
        # "With the 50 SMA/20/10 EMA all coiled up and volatility tightened"
        # EMAs must be converging before the pop
        if not self._are_emals_tightening(df):
            return False

        # 检查是否是收缩楔形（Wedge Pop 必须有楔形底部形态）
        if not self._is_contracting_wedge(recent):
            return False

        recent_low = float(recent["low"].min())

        # 获取前一天的正确bar（修复双bar股票的iloc[-2]问题）
        prev_row = self._get_prev_day_row(df)
        yesterday_close = float(prev_row["close"])
        yesterday_high = float(prev_row["high"])
        bounce_pct = (current - recent_low) / recent_low if recent_low > 0 else 0

        # 反弹至少5%以上
        if bounce_pct < 0.05:
            return False
        # 价格还没反弹太多（不超过50%），避免追涨
        if bounce_pct > 0.50:
            return False

        # 检查是否突破昨天高点（简化：用昨天高点作为突破判断）
        if current <= yesterday_high:
            return False

        # 检查是否站上 EMA（只要求 EMA10 向上，EMA20 企稳即可）
        if not (current > ema10):
            return False
        if not (ema10 > ema10_prev):
            return False

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

        return True

    def get_wedge_info(self, df: pd.DataFrame) -> dict | None:
        """
        返回楔形信息，供 strategy 层计算止损和突破价位。

        PDF（Page 13, 17）：Stop is below the near-term consolidation area.
        不是简单的"昨天最低价"，而是楔形形成期间的整个盘整区间下方。

        放宽：支持反弹形态，不严格要求楔形收敛。
        """
        if len(df) < self.wedge_lookback:
            return None

        lookback = self.wedge_lookback
        recent = df.iloc[-lookback:]

        # 宽松判断：尝试楔形，但如果是反弹形态也接受
        has_wedge = self._is_contracting_wedge(recent)
        current = float(df["close"].iloc[-1])
        recent_low = float(recent["low"].min())

        # 获取前一天的正确bar（修复双bar股票的iloc[-2]问题）
        prev_row = self._get_prev_day_row(df)
        yesterday_high = float(prev_row["high"])
        yesterday_close = float(prev_row["close"])

        # 用楔形上轨或昨天高点作为突破参考
        if has_wedge:
            wedge_upper = self._get_wedge_upper_bound(recent)
        else:
            # 反弹形态：用昨天高点作为突破判断
            wedge_upper = yesterday_high

        # 楔形下轨 = 盘整区间最低点（用于止损）
        wedge_lower = recent_low
        # 突破日的最低价（只有向上突破时才有效）
        breakout_day_low = float(df["low"].iloc[-1]) if current > wedge_upper else 0.0

        return {
            "wedge_upper": wedge_upper,
            "wedge_lower": wedge_lower,   # 止损：below this
            "is_breakout": current > wedge_upper,
            "breakout_day_low": breakout_day_low,
        }

    def _are_emals_tightening(self, df: pd.DataFrame, lookback: int = 10) -> bool:
        """
        Check if EMA10 and EMA20 are tightening (converging).

        Per PDF page 32: "With the 50 SMA/20/10 EMA all coiled up and
        volatility tightened" — EMAs must be converging before Wedge Pop.

        Implementation: The distance between EMA10 and EMA20 should be
        narrowing over the lookback period.
        """
        if len(df) < lookback + 5:
            return False

        ema10_series = df["close"].ewm(span=10).mean()
        ema20_series = df["close"].ewm(span=20).mean()

        # Calculate distance between EMA10 and EMA20 over the lookback
        recent = df.iloc[-lookback:]
        ema10_vals = ema10_series.iloc[-lookback:].values
        ema20_vals = ema20_series.iloc[-lookback:].values

        # Distance = |EMA10 - EMA20| / EMA20
        distances = np.abs(ema10_vals - ema20_vals) / ema20_vals

        # First half average distance vs second half average distance
        mid = lookback // 2
        first_half_avg = np.mean(distances[:mid])
        second_half_avg = np.mean(distances[mid:])

        # Second half should have SMALLER distance (tightening)
        return second_half_avg < first_half_avg * 0.90  # 10%+ narrowing

    def _is_contracting_wedge(self, df: pd.DataFrame) -> bool:
        """
        收缩楔形：高点的连线和高点的连线都朝同一点收敛。
        实现：最近 N 天的最高点不断降低，最低点不断抬高。
        """
        if len(df) < 8:
            return False

        highs = df["high"].values
        lows = df["low"].values
        n = len(highs)

        # 取最近 1/3 和最前 1/3 的高低点比较
        third = n // 3
        recent_highs = highs[-third:]
        older_highs = highs[:third]
        recent_lows = lows[-third:]
        older_lows = lows[:third]

        # 用均值代替极值，避免被单日V形底/尖顶误导
        recent_high_mean = np.mean(recent_highs)
        older_high_mean = np.mean(older_highs)
        recent_low_mean = np.mean(recent_lows)
        older_low_mean = np.mean(older_lows)

        # 收缩：最近波段的高点均值比之前低，低点均值比之前高
        return (recent_high_mean < older_high_mean) and (recent_low_mean > older_low_mean)

    def _get_wedge_upper_bound(self, df: pd.DataFrame) -> float:
        """获取楔形上轨（连接最近高点的趋势线）"""
        highs = df["high"].values
        n = len(highs)
        # 取最近 1/3 最高的两个点的均值（简化趋势线）
        recent_highs = sorted(highs[-n//3:], reverse=True)[:2]
        return np.mean(recent_highs)

    def _is_ema_crossback(self, df: pd.DataFrame, ema10: float, ema20: float,
                           ema10_prev: float, ema20_prev: float) -> bool:
        """
        原文 Identification（Page 11, 20）：
        - "This is not really a step in the Cycle of Price Action, this is
          simply a pullback to the EMAs"
        - "This is the first pullback to the 10/20 EMA and offers a low risk
          buy opportunity to potentially hop on a trend"
        - "Buy against the MA with confirmation"
        - EMAs must be rising (support strengthening)
        - Low volume pullback (not climax selling) — Oliver寻找"dry up"
        - Per page 11: "The more extended you get into a trend, the lower
          the odds are of a pullback entry working"

        两日模式（PDF Page 11, 19-20）：
        - Day 1（回踩日）：缩量下探 EMA，价格靠拢 EMA，低量=抛压枯竭
        - Day 2（确认日）：价格反弹，收阳，收在当日波幅上半部，放量确认

        条件：
        1. EMA10 > 前日EMA10 且 EMA20 > 前日EMA20（上升趋势）
        2. Day 1：价格回落至 EMA10 附近（±2%），低量（≤ 20日均量）
        3. Day 1：最低点必须真正测试 EMA（within ±2%）
        4. Day 2：收盘 > Day 1 收盘（反弹确认）
        5. Day 2：收盘在当日波幅上半部
        6. Day 2：成交量 > Day 1 成交量（放量确认）
        """
        if len(df) < 25:
            return False

        # === CRITICAL (Page 11): Both EMAs must be rising ===
        if not (ema10 > ema10_prev and ema20 > ema20_prev):
            return False

        # ===== Day 1（昨天）：回踩 EMA，低量干涸 =====
        # 使用_get_prev_day_row获取正确的昨天bar（修复双bar股票问题）
        prev_row = self._get_prev_day_row(df)
        y_close = float(prev_row["close"])
        y_low = float(prev_row["low"])
        y_high = float(prev_row["high"])
        y_vol = float(prev_row["volume"])

        # Day 1：价格在【昨日】EMA10 附近（±3%），才算回踩到 EMA 区域
        # 用昨日EMA10判断，而非今日EMA10（今日EMA已随价格上涨而上移）
        if y_close > ema10_prev * 1.03:
            return False  # Day 1 价格没有真正回踩
        if y_close < ema10_prev * 0.97:
            return False  # Day 1 跌破 EMA 太深，不是回踩

        # Day 1：低点可以测试 EMA（允许 ±3% 范围）
        if y_low > ema10_prev * 1.03 or y_low < ema10_prev * 0.97:
            return False  # Day 1 低点没有测试 EMA

        # Day 1：成交量检查已移除（IEX 只占全市场成交量的一部分，
        # 占比稳定时相对变化仍有效，但不再作为触发信号的硬性约束）

        # ===== Day 2（今天）：反弹确认 =====
        t_close = float(df["close"].iloc[-1])
        t_low = float(df["low"].iloc[-1])
        t_high = float(df["high"].iloc[-1])
        t_range = t_high - t_low
        t_vol = float(df["volume"].iloc[-1])

        # Day 2：收盘 > Day 1 收盘（反弹确认）
        if t_close <= y_close:
            return False  # 价格没有反弹

        # Day 2：收盘在当日波幅上半部（买盘涌入）
        if t_range > 0 and t_close < t_low + t_range * 0.5:
            return False  # 收盘在下半部，反弹无力

        # Day 2：收盘 > EMA10
        if t_close <= ema10:
            return False  # 没有真正站上 EMA

        return True

    def _is_base_n_break(self, df: pd.DataFrame) -> bool:
        """
        Base n' Break 入场信号（原文 PDF Page 12, 24-26）。

        PDF原文：
            - "Base n' Break is a multi-week consolidation above the 10/20 EMA"
            - "builds a traditional CAN SLIM Cup n' Handle Pattern"
            - "When we break out of this pattern you can buy with a stop
               below the moving averages"
            - Can add small during consolidation, full size at breakout

        核心逻辑：
            1. 价格在 20 EMA 上方（上升趋势确认）
            2. 盘整期 10-15 天：价格在 EMA 上方横盘，波动范围逐渐收窄（coiling）
            3. 今日：价格放量突破盘整区间最高点（不是 > 昨天收盘）
            4. 成交量 1.2x+ 确认突破

        不再使用"天天低点抬高"这个不合理的条件。
        """
        if len(df) < 20:
            return False

        ema10_series = df["close"].ewm(span=10).mean()
        ema20_series = df["close"].ewm(span=20).mean()
        ema10 = float(ema10_series.iloc[-1])
        ema20 = float(ema20_series.iloc[-1])

        today_close = float(df["close"].iloc[-1])

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

        # === 条件1：价格已在 20 EMA 上方（上升趋势）===
        if today_close < ema20:
            return False

        # === 条件2：盘整区间（最近 lookback 天，排除今日）===
        lookback = self.base_lookback
        consolidation = df.iloc[-(lookback+1):-1]

        # 盘整区间最高点和最低点
        cons_high = float(consolidation["high"].max())
        cons_low = float(consolidation["low"].min())

        # 今日收盘已经突破盘整区间最高点了吗？
        if today_close <= cons_high:
            return False  # 还没突破，不是 Base n' Break

        # === 条件3：盘整期间价格基本在 EMA 上方（不是下跌中横盘）===
        close_vals = consolidation["close"].values
        ema10_vals = ema10_series.iloc[-lookback:].values
        above_ema_count = sum(1 for c, e in zip(close_vals, ema10_vals) if c > e)
        if above_ema_count < lookback * 0.6:
            return False  # 盘整期间超过 40% 时间在 EMA 下方，不是理想形态

        # === 条件4：盘整区间不能太宽（价格基本在收敛）===
        # 区间宽度 / 区间中值 应该 < 15%，太宽说明波动大不是盘整
        mid_price = (cons_high + cons_low) / 2
        if mid_price > 0 and (cons_high - cons_low) / mid_price > 0.15:
            return False  # 区间太宽，不是有效盘整

        # === 条件5：成交量检查已移除 ===
        # IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束

        return True

    def count_pullbacks_since_wedge_pop(self, df: pd.DataFrame) -> int:
        """
        计算从最后一次Wedge Pop至今的回踩次数。

        回踩定义：
        - 价格曾显著高于EMA（代表之前的涨势）
        - 然后价格回落接近EMA（±2%范围）

        返回：回踩次数（0 = 刚发生Wedge Pop还没回踩过）
        """
        if len(df) < 30:
            return 0

        ema10_series = df["close"].ewm(span=10).mean()
        close_arr = df["close"].values
        ema10_arr = ema10_series.values

        pullback_count = 0
        found_first_up = False
        last_pullback_low = 0.0

        # 从最近向历史查找（最多60天）
        for i in range(len(df) - 5, max(0, len(df) - 60), -1):
            current_close = close_arr[i]
            current_ema10 = ema10_arr[i]

            if not found_first_up:
                # 寻找价格显著高于EMA的时刻（Wedge Pop之后的涨势）
                if current_close > current_ema10 * 1.05:
                    found_first_up = True
                continue

            # 已经找到过上涨，现在检测回落到EMA
            if current_close < current_ema10 * 1.02 and current_close > current_ema10 * 0.98:
                # 找到一次回踩到EMA附近
                # 如果这不是连续几天在EMA附近，只算一次
                if last_pullback_low == 0 or (last_pullback_low - current_close) / last_pullback_low > 0.02:
                    pullback_count += 1
                    last_pullback_low = current_close
            elif current_close > current_ema10 * 1.03:
                # 价格再次向上突破，可能开始新一轮上涨
                pass  # 继续往后看

        return pullback_count

    def _is_wedge_drop(self, df: pd.DataFrame, ema10: float, ema20: float,
                        ema10_prev: float, ema20_prev: float) -> bool:
        """
        完整 Wedge Drop 识别（Oliver Kell 体系）：

        1. 前置状态：前一日收盘 > EMA20（多头假象未破）
        2. 均线破坏：当日收盘 < EMA10 且 < EMA20
        3. 结构破坏：收盘 < 近期5日最低点（打破 Higher Low）
        4. 量能验证：放量下跌（>前日 or >20日均量）
        5. 趋势背景：EMA20 > SMA50（上升趋势中的顶部，非延续）
        6. 首次跌破：前日收盘 >= EMA10，今日首次跌破 EMA10
        7. EMA转向：10-EMA 3日斜率 <= 0（均线已开始下行）
        """
        if len(df) < 25:
            return False

        current = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2])

        # 计算附加指标
        ema10_series = df["close"].ewm(span=10, adjust=False).mean()
        sma50 = float(df["close"].rolling(50).mean().iloc[-1])
        vol_sma20 = float(df["volume"].rolling(20).mean().iloc[-1])
        recent_low_5d = float(df["low"].rolling(5).min().shift(1).iloc[-1])

        # 1. 前置状态：前一天还在 EMA20 之上（维持多头）
        prev_holding_support = prev_close > ema20

        # 2. 均线破坏：阴线实体收在 EMA10 和 EMA20 之下
        ema_breakdown = (current < ema10) and (current < ema20)

        # 3. 结构破坏：打破近期震荡区间 Lower Low
        structure_breakdown = current < recent_low_5d

        # 4. 量能验证：放量确认机构派发
        volume = float(df["volume"].iloc[-1])
        prev_volume = float(df["volume"].iloc[-2])
        distribution_volume = (volume > prev_volume) or (volume > vol_sma20)

        # 5. 趋势背景：上升趋势中的顶部（EMA20 在 SMA50 之上）
        uptrend_context = ema20 > sma50

        # 6. 首次跌破：前日收盘 >= 前日EMA10，今日跌破今日EMA10
        # 注意：跳空低开的情况，前日收盘可能已在EMA10下方，但今日大跌继续创新低，
        # 也视为有效跌破（EMA趋势已转向+价格继续下行即可）
        first_break_original = (prev_close >= ema10_prev) and (current < ema10)
        first_break_gapdown = (prev_close < ema10_prev) and (current < prev_close) and (current < ema10)
        first_break = first_break_original or first_break_gapdown

        # 7. EMA转向：10-EMA 3日斜率 <= 0（均线已开始下行）
        ema10_slope = float(ema10_series.diff(3).iloc[-1])
        ema_turning_down = ema10_slope <= 0

        return (
            prev_holding_support and
            ema_breakdown and
            structure_breakdown and
            distribution_volume and
            uptrend_context and
            first_break and
            ema_turning_down
        )

    def _is_reversal_extension(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification（Pages 12-14）：
        - Clear support on high timeframe (e.g., 200 SMA)
        - Extreme extension away from EMA on low timeframe (10%+)
        - Heavy volume capitulation on reversal bar (CRITICAL - page 12)
        - Sharp snap-back toward EMA after heavy volume decline

        Rule: Do NOT buy here. Wait for confirmation signals.
        """
        if len(df) < 25:
            return False

        current = float(df["close"].iloc[-1])
        prev_row = self._get_prev_day_row(df)
        yesterday_close = float(prev_row["close"])
        ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])
        today_volume = float(df["volume"].iloc[-1])

        # 远离 EMA（8%+，与 Exhaustion Extension 一致；2026-08-14 从 10% 放宽到 8% 以增加信号频率）
        ema_dist = abs(current - ema20) / ema20
        if ema_dist < 0.08:
            return False

        # === 成交量检查已移除 ===
        # IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束

        # 快速反弹信号（当天从低位反弹 > 3%）
        day_change = (current - yesterday_close) / yesterday_close
        if day_change < 0.03:
            return False

        # === Higher timeframe support check (e.g., near 200 SMA) ===
        if len(df) >= 200:
            sma200 = float(df["close"].rolling(200).mean().iloc[-1])
            # Price should be near 200 SMA (within 15%)
            if current > sma200 * 1.15:
                return False

        return True

    def get_current_stage(self, df: pd.DataFrame) -> CycleStage:
        """alias for classify()"""
        return self.classify(df)

    # ─── 周K EMA 趋势识别 ────────────────────────────────────────────────

    def get_weekly_ema(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        从日K数据重采样生成周K数据，并计算周K EMA10/EMA20。

        返回：含 open, high, low, close, volume, EMA10, EMA20 列的 DataFrame
        """
        if len(df) < 30:
            return pd.DataFrame()

        # 周K重采样：每周截至周五（美国股市标准）
        weekly = df.resample("W-FRI").agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }).dropna()

        if weekly.empty:
            return pd.DataFrame()

        # 计算周K EMA
        weekly["EMA10"] = weekly["close"].ewm(span=10).mean()
        weekly["EMA20"] = weekly["close"].ewm(span=20).mean()

        return weekly

    def is_weekly_uptrend(self, df: pd.DataFrame) -> bool:
        """
        检查周K趋势是否确认上升。

        Oliver Kell 原则：先看周线做过滤 (Filter & Confirm)
        - 周线 EMA10 > EMA20（多头排列）
        - 周线 EMA10 和 EMA20 都处于上升趋势
        - 价格在周线 EMA10 和 EMA20 之上

        只有周K趋势确认，才在日K上产生买入信号。
        """
        weekly = self.get_weekly_ema(df)
        if weekly.empty or len(weekly) < 10:
            return False

        ema10 = float(weekly["EMA10"].iloc[-1])
        ema20 = float(weekly["EMA20"].iloc[-1])
        ema10_prev = float(weekly["EMA10"].iloc[-2])
        ema20_prev = float(weekly["EMA20"].iloc[-2])
        price = float(weekly["close"].iloc[-1])

        # 周线 EMA10 > EMA20（多头排列）
        if ema10 <= ema20:
            return False

        # 周线 EMA10 和 EMA20 都在上升
        if ema10 <= ema10_prev or ema20 <= ema20_prev:
            return False

        # 价格在周线 EMA10 和 EMA20 之上
        if price < ema10 or price < ema20:
            return False

        return True

    # ─── SMA 多头排列检查（Perfect Stack）───────────────────────────────

    def is_perfect_stack(self, df: pd.DataFrame) -> bool:
        """
        检查是否处于完美多头排列（Perfect Stack）。

        Oliver Kell 核心原则：Price > 10 EMA > 20 EMA，且两者都在上升。
        PDF 不要求 SMA50 > SMA200 作为入场条件（那是长期趋势指标，不是入场条件）。

        数据不足 50 天时返回 False。
        """
        if len(df) < 50:
            return False

        current = float(df["close"].iloc[-1])
        ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
        ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])

        # Price > EMA10 > EMA20 且两者都在上升
        ema10_prev = float(df["close"].ewm(span=10).mean().iloc[-2])
        ema20_prev = float(df["close"].ewm(span=20).mean().iloc[-2])

        return (
            current > ema10 > ema20
            and ema10 > ema10_prev
            and ema20 > ema20_prev
        )

    def is_bullish_alignment(self, df: pd.DataFrame) -> bool:
        """
        检查是否处于看涨排列（至少满足 Price > EMA10 > EMA20）。

        作为 Perfect Stack 的宽松版本，用于数据不足 50 天时。
        只要求 Price > EMA10 > EMA20 且两者都在上升，不要求 SMA50。
        """
        if len(df) < 20:
            return False

        current = float(df["close"].iloc[-1])
        ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
        ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])
        ema10_prev = float(df["close"].ewm(span=10).mean().iloc[-2])
        ema20_prev = float(df["close"].ewm(span=20).mean().iloc[-2])

        # 价格 > EMA10 > EMA20 且两者都在上升
        return (
            current > ema10 > ema20
            and ema10 > ema10_prev
            and ema20 > ema20_prev
        )

    def is_above_sma50(self, df: pd.DataFrame) -> bool:
        """检查价格是否在 SMA50 之上"""
        if len(df) < 50:
            return False
        current = float(df["close"].iloc[-1])
        sma50 = float(df["close"].rolling(50).mean().iloc[-1])
        return current > sma50

    def is_above_sma200(self, df: pd.DataFrame) -> bool:
        """检查价格是否在 SMA200 之上（判断牛熊分界）"""
        if len(df) < 200:
            return False
        current = float(df["close"].iloc[-1])
        sma200 = float(df["close"].rolling(200).mean().iloc[-1])
        return current > sma200

    # ─── RS（相对强度）计算 ────────────────────────────────────

    def compute_rs_line(self, df: pd.DataFrame, benchmark: pd.DataFrame) -> pd.Series:
        """
        计算相对强度（RS）：过去 20 个交易日个股涨幅 / 大盘（SPY）涨幅（倍数）。

        公式：
            RS = (stock_close / stock_close_20d_ago) / (bench_close / bench_close_20d_ago)

        含义（倍数形式）：
            - RS = 1.0 ：个股与大盘涨幅相同（同步大盘）
            - RS > 1.0 ：个股过去 20 天跑赢大盘
            - RS < 1.0 ：个股过去 20 天跑输大盘

        返回：RS Series（倍数形式，首 20 个交易日值为 1.0 兜底）
        """
        if len(df) < 21 or len(benchmark) < 21:
            return pd.Series([1.0], index=df.index[:1])

        # 对齐数据：df 和 benchmark 都 reindex 到共同 index
        aligned_df, aligned_bench = df.align(benchmark, join="inner")
        if aligned_df.empty or aligned_bench.empty or len(aligned_df) < 21:
            return pd.Series([1.0], index=df.index[:1])

        # 20 日前收盘价（shift 后，shift(20) 取 20 个交易日之前）
        stock_close = aligned_df["close"]
        bench_close = aligned_bench["close"]
        stock_close_20d_ago = stock_close.shift(20)
        bench_close_20d_ago = bench_close.shift(20)

        # 各自涨幅比 = 今天 / 20 天前
        stock_gain_ratio = stock_close / stock_close_20d_ago
        bench_gain_ratio = bench_close / bench_close_20d_ago

        # 相对强度 = 个股涨幅 / 大盘涨幅（倍数形式，不 ×100）
        rs = stock_gain_ratio / bench_gain_ratio

        # 前 20 个交易日没有 20 天前的数据 → NaN；用 1.0 兜底（即"与大盘同步"）
        rs = rs.fillna(1.0)
        return rs

    def compute_rs_line_long(self, df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 50) -> pd.Series:
        """
        计算长周期相对强度（RS Long）：过去 N 个交易日个股涨幅 / 大盘涨幅（倍数）。

        常用于 10 周（50 个交易日）相对强度。

        公式：RS = (stock_close / stock_close_Nd_ago) / (bench_close / bench_close_Nd_ago)
              RS = 1.0 表示与大盘同步，RS > 1.0 表示跑赢，RS < 1.0 表示跑输

        返回：RS Series（倍数形式，前 lookback 个交易日值为 1.0 兜底）
        """
        if len(df) < lookback + 1 or len(benchmark) < lookback + 1:
            return pd.Series([1.0], index=df.index[:1])

        aligned_df, aligned_bench = df.align(benchmark, join="inner")
        if aligned_df.empty or aligned_bench.empty or len(aligned_df) < lookback + 1:
            return pd.Series([1.0], index=df.index[:1])

        stock_close = aligned_df["close"]
        bench_close = aligned_bench["close"]
        stock_close_n_ago = stock_close.shift(lookback)
        bench_close_n_ago = bench_close.shift(lookback)

        stock_gain_ratio = stock_close / stock_close_n_ago
        bench_gain_ratio = bench_close / bench_close_n_ago

        rs = stock_gain_ratio / bench_gain_ratio
        rs = rs.fillna(1.0)
        return rs

    def compute_rs_line_short(self, df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 10) -> pd.Series:
        """
        计算短期相对强度（RS Short）：过去 N 个交易日个股涨幅 / 大盘涨幅（倍数）。

        常用于 10 日（约 2 周）短期相对强度。

        公式：RS = (stock_close / stock_close_Nd_ago) / (bench_close / bench_close_Nd_ago)
              RS = 1.0 表示与大盘同步，RS > 1.0 表示短期跑赢，RS < 1.0 表示短期跑输

        返回：RS Series（倍数形式，前 lookback 个交易日值为 1.0 兜底）
        """
        if len(df) < lookback + 1 or len(benchmark) < lookback + 1:
            return pd.Series([1.0], index=df.index[:1])

        aligned_df, aligned_bench = df.align(benchmark, join="inner")
        if aligned_df.empty or aligned_bench.empty or len(aligned_df) < lookback + 1:
            return pd.Series([1.0], index=df.index[:1])

        stock_close = aligned_df["close"]
        bench_close = aligned_bench["close"]
        stock_close_n_ago = stock_close.shift(lookback)
        bench_close_n_ago = bench_close.shift(lookback)

        stock_gain_ratio = stock_close / stock_close_n_ago
        bench_gain_ratio = bench_close / bench_close_n_ago

        rs = stock_gain_ratio / bench_gain_ratio
        rs = rs.fillna(1.0)
        return rs

    def compute_volume_ratio(self, df: pd.DataFrame, lookback: int = 20) -> float | None:
        """
        计算量比：今日成交量 / 过去 N 日均量（不含今日）。

        参数：
            df:        含 'volume' 列的 DataFrame
            lookback:  均量窗口（默认 20）

        返回：
            浮点比例（如 1.5 表示今天量是均量的 1.5 倍），数据不足返回 None
        """
        if "volume" not in df.columns:
            return None
        if len(df) < lookback + 1:
            return None
        today_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[-(lookback + 1):-1].mean())
        if avg_vol <= 0:
            return None
        return today_vol / avg_vol

    def is_rs_leading(self, df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 20) -> bool:
        """
        检查 RS Line 是否领先大盘（开始走强）。

        原文（PDF pages 15-17, 28）：RS Line = stock / benchmark * 100。
        "Buy the strongest stocks on a relative basis will lead to the greatest future returns."

        实现（两个条件满足其一即可）：
            1. RS Line 创 20 天新高（strong confirmation）
            2. RS Line 在其 20 日均线上方（确认上升趋势）
        """
        if len(df) < lookback + 5 or len(benchmark) < lookback + 5:
            return False

        rs = self.compute_rs_line(df, benchmark)

        # === 条件 1：RS Line 创 20 天新高 ===
        rs_recent = rs.iloc[-lookback:]
        rs_current = rs.iloc[-1]
        rs_max = rs_recent.max()
        is_20day_high = rs_current >= rs_max * 0.999

        # === 条件 2：RS Line 在 20 日均线上方 ===
        rs_20ma = rs.rolling(20).mean()
        rs_20ma_current = float(rs_20ma.iloc[-1])
        is_above_20ma = rs_current > rs_20ma_current

        return is_20day_high or is_above_20ma

    # ─── Variant Patterns（Base n' Break 变体形态）───────────────────────

    def is_vcp(self, df: pd.DataFrame) -> bool:
        """
        VCP (Volatility Contraction Pattern) 检测。

        原文：VCP = Volatility Contraction Pattern
        价格在基底内波动率逐步收缩（range 越来越小），然后放量突破。

        识别：
            - 价格在盘整期内，波动率（最高-最低）/ 最低价 逐渐缩小
            - 通常有 2-4 次收缩（每次收缩后小幅反弹）
            - 最后一次收缩后放量突破
        """
        if len(df) < 30:
            return False

        # 检查最近 N 天的波动率是否在收缩
        lookback = 20
        recent = df.iloc[-lookback:]

        # 把最近的时间分成3段，检查波动率是否逐段缩小
        third = lookback // 3
        segment1 = recent.iloc[:third]
        segment2 = recent.iloc[third:2*third]
        segment3 = recent.iloc[2*third:]

        def volatility(s):
            return (s["high"].max() - s["low"].min()) / s["low"].min()

        vol1 = volatility(segment1)
        vol2 = volatility(segment2)
        vol3 = volatility(segment3)

        # 波动率应该逐段收缩（vol3 < vol2 < vol1）
        if not (vol3 < vol2 < vol1):
            return False

        # 最后一段的波动率应该 < 8%（紧凑）
        if vol3 > 0.08:
            return False

        # 今天的收盘价应该在段3的高点之上（突破）
        current = float(df["close"].iloc[-1])
        seg3_high = float(segment3["high"].max())

        if current <= seg3_high:
            return False

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

        return True

    def is_bull_flag(self, df: pd.DataFrame) -> bool:
        """
        Bull Flag 检测（改进版，per PDF pages 34, 46）。

        原文关键要求：
            - "Price finds support as the 10 EMA catches up to price"
            - "Price pulls back into the moving averages and provides a low risk-spot"
            - 旗面期间，价格必须回踩 EMA10/EMA20（找到支撑）

        形态：
            1. 旗杆：15%+ 强势上涨，且期间价格位于 EMA10/EMA20 之上
            2. 旗面：最近 5-10 天小幅盘整，范围 < 8%
            3. 关键改进：旗面期间价格低点必须触及或接近 EMA10/EMA20（3% 以内）
            4. EMA10 仍在上升或走平（未被跌破）
            5. 今天放量突破旗形上轨（1.2x+）
        """
        if len(df) < 20:
            return False

        # 计算 EMA10/EMA20 系列
        ema10_series = df["close"].ewm(span=10).mean()
        ema20_series = df["close"].ewm(span=20).mean()

        # ============================================================
        # 1. 旗杆检查：前 10-20 天有一波 15%+ 上涨，且价格位于 EMA10/EMA20 之上
        # ============================================================
        pole_start = len(df) - 20
        pole_end = len(df) - 5

        if pole_start < 0:
            return False

        pole_df = df.iloc[pole_start:pole_end]
        pole_high = float(pole_df["high"].max())
        pole_low = float(pole_df["low"].min())

        # 旗杆涨幅 > 15%
        pole_gain = (pole_high - pole_low) / pole_low
        if pole_gain < 0.15:
            return False

        # 旗杆期间，价格必须始终位于 EMA10/EMA20 之上
        pole_ema10_vals = ema10_series.iloc[pole_start:pole_end].values
        pole_ema20_vals = ema20_series.iloc[pole_start:pole_end].values
        pole_close_vals = pole_df["close"].values
        pole_high_vals = pole_df["high"].values

        # 至少在大部分日子（80%+）价格高于 EMA
        above_ema10_count = sum(c > e10 * 0.99 for c, e10 in zip(pole_close_vals, pole_ema10_vals))
        above_ema20_count = sum(c > e20 * 0.99 for c, e20 in zip(pole_close_vals, pole_ema20_vals))
        if above_ema10_count < len(pole_close_vals) * 0.8:
            return False
        if above_ema20_count < len(pole_close_vals) * 0.8:
            return False

        # ============================================================
        # 2. 旗面检查：最近 5-10 天盘整，范围 < 8%
        # ============================================================
        flag_df = df.iloc[-10:]
        flag_high = float(flag_df["high"].max())
        flag_low = float(flag_df["low"].min())

        # 旗面高点不能超过旗杆高点（避免旗杆被侵蚀）
        if flag_high > pole_high * 0.97:
            return False

        # 旗面范围应该紧凑（< 8%）
        flag_range = (flag_high - flag_low) / flag_low
        if flag_range > 0.08:
            return False

        # ============================================================
        # 3. 关键改进：旗面期间价格必须回踩 EMA10/EMA20
        #    PDF: "Price finds support as the 10 EMA catches up to price"
        #         "Price pulls back into the moving averages"
        # ============================================================
        flag_ema10_vals = ema10_series.iloc[-10:].values
        flag_ema20_vals = ema20_series.iloc[-10:].values
        flag_low_vals = flag_df["low"].values

        # 检查旗面期间是否至少有低点触及 EMA（3% 以内）
        touched_ema10 = any(
            low <= ema10 * 1.03 and low >= ema10 * 0.97
            for low, ema10 in zip(flag_low_vals, flag_ema10_vals)
        )
        touched_ema20 = any(
            low <= ema20 * 1.03 and low >= ema20 * 0.97
            for low, ema20 in zip(flag_low_vals, flag_ema20_vals)
        )

        # 至少要触及其中一个 EMA（最好是 EMA10）
        if not touched_ema10 and not touched_ema20:
            return False

        # ============================================================
        # 4. EMA10 仍在上升或走平（未被跌破）
        # ============================================================
        ema10_current = float(ema10_series.iloc[-1])
        ema10_prev = float(ema10_series.iloc[-2])
        ema10_prev_prev = float(ema10_series.iloc[-3])

        # EMA10 必须在上升或走平，不能明显下降
        # 如果连续 2 天下降，则 EMA10 已破
        if ema10_current < ema10_prev and ema10_prev < ema10_prev_prev:
            return False

        # ============================================================
        # 5. 今天收盘价突破旗形上轨
        # ============================================================
        current = float(df["close"].iloc[-1])
        if current <= flag_high:
            return False

        # ============================================================
        # 6. 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）
        # ============================================================

        return True

    # ─── Candlestick Sell Signals（Pages 19, 20, 23, 31, 34）───────────────

    def is_shooting_star(self, df: pd.DataFrame) -> bool:
        """
        Shooting Star (Page 20, 31, 34):
        Bearish reversal candle after an advance.

        Identification:
            - Yesterday + today both bullish advance (price going up)
            - Today: opens higher (gap up), trades higher, then closes near the low
            - Body is at the top of the candle, long upper wick
            - Body small relative to total range

        This is a SELL signal when detected in existing positions.
        """
        if len(df) < 2:
            return False

        today = df.iloc[-1]
        yesterday = self._get_prev_day_row(df)

        today_open = float(today["open"])
        today_close = float(today["close"])
        today_high = float(today["high"])
        today_low = float(today["low"])

        yesterday_open = float(yesterday["open"])
        yesterday_close = float(yesterday["close"])

        # === Must have bullish advance: yesterday was bullish ===
        if yesterday_close <= yesterday_open:
            return False

        # === Today must also be bullish (close > open) ===
        if today_close <= today_open:
            return False

        # === Gap up: today opens above yesterday's high ===
        if today_open <= yesterday_close:
            return False

        # === Closes near the low (bearish reversal): close near open ===
        body = abs(today_close - today_open)
        total_range = today_high - today_low
        if total_range == 0:
            return False

        # Body should be small relative to total range (< 30%)
        if body / total_range >= 0.30:
            return False

        # === Upper wick is long (rejection of higher prices) ===
        upper_wick = today_high - max(today_open, today_close)
        if upper_wick < body:  # Upper wick should exceed body
            return False

        # === Close near the low (close in bottom 40% of range) ===
        distance_from_low = today_close - today_low
        if distance_from_low / total_range > 0.40:
            return False

        return True

    def is_bearish_engulfing(self, df: pd.DataFrame) -> bool:
        """
        Bearish Engulfing (Page 23, 34):
        Bearish reversal pattern where today's bearish body "engulfs" yesterday's bullish body.

        Identification:
            - Yesterday: small bullish candle
            - Today: bearish candle (close < open)
            - Today opens ABOVE yesterday's close
            - Today closes BELOW yesterday's open
            - The bearish body fully engulfs the bullish body

        This is a SELL signal when detected in existing positions.
        """
        if len(df) < 2:
            return False

        today = df.iloc[-1]
        yesterday = self._get_prev_day_row(df)

        today_open = float(today["open"])
        today_close = float(today["close"])
        today_high = float(today["high"])
        today_low = float(today["low"])

        yesterday_open = float(yesterday["open"])
        yesterday_close = float(yesterday["close"])
        yesterday_high = float(yesterday["high"])
        yesterday_low = float(yesterday["low"])

        # === Yesterday: small bullish candle ===
        if yesterday_close <= yesterday_open:
            return False

        yesterday_body = abs(yesterday_close - yesterday_open)
        yesterday_range = yesterday_high - yesterday_low
        if yesterday_range == 0:
            return False
        # Body should be small relative to its range (< 40%)
        if yesterday_body / yesterday_range >= 0.40:
            return False

        # === Today: bearish candle ===
        if today_close >= today_open:
            return False

        # === Gap up: today opens above yesterday's close ===
        if today_open <= yesterday_close:
            return False

        # === Closes below yesterday's open: bearish engulfs ===
        if today_close >= yesterday_open:
            return False

        # === Today's body engulfs yesterday's body ===
        today_body = abs(today_close - today_open)
        if today_body <= yesterday_body:
            return False

        return True

    def is_evening_star_doji(self, df: pd.DataFrame) -> bool:
        """
        Evening Star Doji (Page 19):
        Three-candle bearish reversal pattern.

        Identification:
            - Candle 1: bullish (price goes up)
            - Candle 2: doji (open ≈ close, very small body) — the "star"
            - Candle 3: bearish candle confirming reversal
            - Gap between candle 1 and 2, and between 2 and 3 ideally

        This is a SELL signal when detected in existing positions.
        """
        if len(df) < 3:
            return False

        candle1 = df.iloc[-3]
        candle2 = df.iloc[-2]
        candle3 = df.iloc[-1]

        c1_open = float(candle1["open"])
        c1_close = float(candle1["close"])

        c2_open = float(candle2["open"])
        c2_close = float(candle2["close"])
        c2_high = float(candle2["high"])
        c2_low = float(candle2["low"])

        c3_open = float(candle3["open"])
        c3_close = float(candle3["close"])

        # === Candle 1: bullish (price goes up) ===
        if c1_close <= c1_open:
            return False

        # === Candle 2: doji (open ≈ close, small body) ===
        c2_body = abs(c2_close - c2_open)
        c2_range = c2_high - c2_low
        if c2_range == 0:
            return False

        # Body should be very small relative to range (< 20%)
        if c2_body / c2_range >= 0.20:
            return False

        # Doji should have some wick on both sides (not just a tiny range bar)
        upper_wick = c2_high - max(c2_open, c2_close)
        lower_wick = min(c2_open, c2_close) - c2_low
        if upper_wick < c2_body * 0.5 and lower_wick < c2_body * 0.5:
            return False

        # === Candle 3: bearish confirming reversal ===
        if c3_close >= c3_open:
            return False

        # === Gap logic: candle 2 should gap away from candle 1 ===
        # Candle 2 low should be above candle 1 close (gap up)
        c2_low_val = float(candle2["low"])
        if c2_low_val <= c1_close:
            return False

        # === Candle 3 should gap down from candle 2 ===
        # Candle 3 open should be below candle 2 high
        c3_high = float(candle3["high"])
        if c3_open >= c2_high:
            return False

        return True

    # ─── Ignite Bar Detection（用于追踪止损管理）───────────────────────────

    def detect_ignite_bar(self, df: pd.DataFrame) -> float:
        """
        检测 Ignite Bar。

        原文（PDF pages 25, 32-33）：
            "When we see an Ignite Bar low, we want to adjust our stops to
             the low of that bar."

        Ignite Bar 定义：
            - 今日是看涨蜡烛线（close > open）
            - 今日区间幅度 >= 3%（(high - low) / low > 0.03）
            - 成交量 >= 1.5x 20日均量

        返回：Ignite Bar 的 LOW 价格；未检测到返回 0.0
        """
        if len(df) < 21:
            return 0.0

        today = df.iloc[-1]
        today_open = float(today["open"])
        today_high = float(today["high"])
        today_low = float(today["low"])
        today_close = float(today["close"])
        today_volume = float(today["volume"])

        # 必须是看涨蜡烛线
        if today_close <= today_open:
            return 0.0

        # 区间幅度 >= 3%
        day_range = (today_high - today_low) / today_low
        if day_range < 0.03:
            return 0.0

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

        return today_low

    def is_bull_pennant(self, df: pd.DataFrame) -> bool:
        """
        Bull Pennant 检测。

        原文：Bull Pennant = 与 Bull Flag 类似，但旗面是收敛的三角形而非矩形。
        形态：
            - 前期有一波强势上涨（旗杆）
            - 然后价格小幅收窄，形成三角形盘整
            - 三角形上轨下降，下轨上升（或横盘）
            - 放量突破三角形上轨
        """
        if len(df) < 20:
            return False

        # 找旗杆：前 10-20 天有一波显著上涨（> 15%）
        pole_start = len(df) - 20
        pole_end = len(df) - 5

        if pole_start < 0:
            return False

        pole_df = df.iloc[pole_start:pole_end]
        pole_high = float(pole_df["high"].max())
        pole_low = float(pole_df["low"].min())

        # 旗杆涨幅 > 15%
        pole_gain = (pole_high - pole_low) / pole_low
        if pole_gain < 0.15:
            return False

        # 旗面：最近 5-10 天的收敛盘整
        pennant_df = df.iloc[-10:]
        pennant_highs = pennant_df["high"].values
        pennant_lows = pennant_df["low"].values

        # 三角形收敛：最近的高低差应该比早期小
        early_range = pennant_highs[:5].max() - pennant_lows[:5].min()
        late_range = pennant_highs[-5:].max() - pennant_lows[-5:].min()

        if late_range >= early_range * 0.8:
            return False

        # 三角形收敛方向检查
        recent_high_trend = pennant_highs[-1] - pennant_highs[0]
        recent_low_trend = pennant_lows[-1] - pennant_lows[0]

        if not (recent_high_trend < 0 and recent_low_trend >= 0):
            return False

        # 突破三角形上轨
        triangle_upper = float(pennant_df["high"].max())
        current = float(df["close"].iloc[-1])

        if current <= triangle_upper:
            return False

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

        return True