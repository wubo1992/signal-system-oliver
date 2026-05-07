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
    EMA_CROSSBACK = "ema_crossback"
    BASE_N_BREAK = "base_n_break"
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
        if len(df) < 50:
            return CycleStage.UNKNOWN

        current = float(df["close"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])

        # 前一天的值
        ema10_prev = float(df["EMA10"].iloc[-2])
        ema20_prev = float(df["EMA20"].iloc[-2])

        # EMA 斜率
        ema10_slope = ema10 - ema10_prev
        ema20_slope = ema20 - ema20_prev

        # 1. Exhaustion Extension 检测（价格远离 EMA）
        if self._is_exhaustion_extension(df):
            return CycleStage.EXHAUSTION_EXTENSION

        # 2. Wedge Pop 检测（突破 wedge 上轨 + 站上 EMA）
        if self._is_wedge_pop(df, ema10, ema20, ema10_prev, ema20_prev):
            return CycleStage.WEDGE_POP

        # 3. EMA Crossback 检测（回踩 EMA）
        if self._is_ema_crossback(df, ema10, ema20, ema10_prev, ema20_prev):
            return CycleStage.EMA_CROSSBACK

        # 4. Base n' Break 检测（盘整后突破）
        if self._is_base_n_break(df):
            return CycleStage.BASE_N_BREAK

        # 5. Wedge Drop 检测（跌破 EMA）
        if self._is_wedge_drop(df, ema10, ema20, ema10_prev, ema20_prev):
            return CycleStage.WEDGE_DROP

        # 6. Reversal Extension 检测（底部信号）
        if self._is_reversal_extension(df):
            return CycleStage.REVERSAL_EXTENSION

        return CycleStage.UNKNOWN

    def _is_exhaustion_extension(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Price far from 10/20 EMA (typically 30-50%+)
        - Volume shows climax run
        - Distance to EMA exceeds historical normal range
        """
        if len(df) < 30:
            return False

        current = float(df["close"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])

        # 价格远离 EMA 的比例
        ema_dist = abs(current - ema20) / ema20
        ema10_dist = abs(current - ema10) / ema10

        # 30%+ 远离
        if ema_dist < 0.30 and ema10_dist < 0.30:
            return False

        # 放量确认（climax run）
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return ema_dist > 0.30 and vol_ratio > 1.5

    def _is_wedge_pop(self, df: pd.DataFrame, ema10: float, ema20: float,
                       ema10_prev: float, ema20_prev: float) -> bool:
        """
        原文 Identification：
        - Price bounces from low, consolidates in contracting Wedge
        - Price breaks Wedge upper bound AND crosses above 10/20 EMA
        - Volume expansion (accumulation confirmation)
        """
        if len(df) < self.wedge_lookback + 5:
            return False

        lookback = self.wedge_lookback
        recent = df.iloc[-lookback:]

        current = float(df["close"].iloc[-1])

        # 检查价格是否在收缩楔形中
        if not self._is_contracting_wedge(recent):
            return False

        # 检查是否突破上轨
        wedge_high = self._get_wedge_upper_bound(recent)
        if current <= wedge_high:
            return False

        # 检查是否站上 EMA（且 EMA 向上）
        if not (current > ema10 and current > ema20):
            return False
        if not (ema10 > ema10_prev and ema20 > ema20_prev):
            return False

        # 放量确认
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio >= 1.5

    def _is_contracting_wedge(self, df: pd.DataFrame) -> bool:
        """
        收缩楔形：高点的连线和高点的连线都朝同一点收敛。
        实现：检查最近 N 天的高低点连线是否收敛。
        """
        if len(df) < 10:
            return False

        highs = df["high"].values
        lows = df["low"].values

        # 取前半段和后半段的平均高低点
        mid = len(highs) // 2
        first_half_high = np.mean(highs[:mid])
        second_half_high = np.mean(highs[mid:])
        first_half_low = np.mean(lows[:mid])
        second_half_low = np.mean(lows[mid:])

        # 收缩：后半段高点 < 前半段高点，且后半段低点 > 前半段低点
        return (second_half_high < first_half_high) and (second_half_low > first_half_low)

    def _get_wedge_upper_bound(self, df: pd.DataFrame) -> float:
        """获取楔形上轨（连接最近高点的趋势线）"""
        highs = df["high"].values
        # 简单实现：取最近 1/3 的最高点
        n = len(highs)
        return np.max(highs[n // 3:])

    def _is_ema_crossback(self, df: pd.DataFrame, ema10: float, ema20: float,
                           ema10_prev: float, ema20_prev: float) -> bool:
        """
        原文 Identification：
        - After Wedge Pop, price gently pulls back to 10/20 EMA
        - Pullback is slow, low volume (not sharp drop)
        - EMAs are now upward-sloping (support strengthening)
        """
        if len(df) < 25:
            return False

        current = float(df["close"].iloc[-1])

        # EMA 必须在上升
        if not (ema10 > ema10_prev and ema20 > ema20_prev):
            return False

        # 价格回踩 EMA（允许略低于 EMA 但不能太远）
        if not (current >= ema20 * 0.97):  # 3% 以内算回踩
            return False

        # 回踩速度慢（当天跌幅 < 2%）
        current_prev = float(df["close"].iloc[-2])
        if current_prev == 0:
            return False
        drop_pct = (current_prev - current) / current_prev
        if drop_pct > 0.02:
            return False  # 跌幅太大，不是"slow pullback"

        # 量能低（不是放量急跌）
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio < 1.2  # 低量回调

    def _is_base_n_break(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Price consolidates for weeks (2-4 weeks), volume dries up
        - EMAs compress toward price during consolidation
        - Price holds Higher Lows above EMAs
        - Breaks upper consolidation bound with volume expansion
        """
        if len(df) < self.base_lookback + 5:
            return False

        lookback = self.base_lookback
        recent = df.iloc[-lookback:]

        # 检查是否在盘整（波动范围收窄）
        price_range = (recent["high"].max() - recent["low"].min()) / recent["low"].min()
        if price_range > 0.15:  # 盘整区间应 < 15%
            return False

        # 检查量能萎缩（volume exhaustion）
        vol_recent = float(recent["volume"].iloc[-5:].mean())
        vol_older = float(df["volume"].iloc[-lookback:-5].mean())
        if vol_older == 0:
            return False
        if vol_recent >= vol_older * 0.8:  # 没有萎缩
            return False

        # 检查是否突破盘整区间上轨
        current = float(df["close"].iloc[-1])
        consolidation_high = float(recent["high"].max())
        if current <= consolidation_high:
            return False

        # 突破时放量
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio >= 1.5

    def _is_wedge_drop(self, df: pd.DataFrame, ema10: float, ema20: float,
                        ema10_prev: float, ema20_prev: float) -> bool:
        """
        原文 Identification：
        - Price breaks below 10/20 EMA with increasing supply
        - EMAs start downward slope
        """
        if len(df) < 5:
            return False

        current = float(df["close"].iloc[-1])

        # 跌破 EMA
        if not (current < ema10 and current < ema20):
            return False

        # EMA 向下
        if not (ema10 < ema10_prev and ema20 < ema20_prev):
            return False

        return True

    def _is_reversal_extension(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Clear support on high timeframe
        - Extreme extension away from EMA on low timeframe
        - Sharp snap-back toward EMA after heavy volume decline
        - Volume shows divergence signs

        Rule: Do NOT buy here. Wait for confirmation signals.
        """
        if len(df) < 30:
            return False

        current = float(df["close"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])

        # 远离 EMA（30%+）
        ema_dist = abs(current - ema20) / ema20
        if ema_dist < 0.30:
            return False

        # 快速反弹信号（当天从低位反弹 > 3%）
        day_change = (current - float(df["close"].iloc[-2])) / float(df["close"].iloc[-2])
        if day_change < 0.03:
            return False

        return True

    def get_current_stage(self, df: pd.DataFrame) -> CycleStage:
        """alias for classify()"""
        return self.classify(df)