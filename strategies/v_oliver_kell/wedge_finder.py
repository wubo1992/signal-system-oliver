"""
strategies/v_oliver_kell/wedge_finder.py

Wedge（楔形）形态识别（原文 Section 2.1 ② Wedge Pop）：

收缩楔形（Contracting Wedge）：
    - 高点的连线和低点的连线都朝同一点收敛
    - 价格在楔形内振荡，波动范围逐渐收窄
    - 向上突破楔形上轨 = Wedge Pop 信号

扩张楔形（Expanding Wedge）：
    - 高低点都朝外扩散（较少见）
    - 向下突破楔形下轨 = Wedge Drop 信号
"""

from dataclasses import dataclass
from enum import Enum
import numpy as np
import pandas as pd


class WedgeType(Enum):
    CONTRACTING = "contracting"
    EXPANDING = "expanding"
    NONE = "none"


@dataclass
class WedgeResult:
    wedge_type: WedgeType
    upper_bound: float      # 楔形上轨（高点连线）
    lower_bound: float     # 楔形下轨（低点连线）
    breakout_detected: bool
    breakout_direction: str  # "up" or "down" or None
    breakout_day_low: float  # 突破日的最低价（用于设置止损）


class WedgeFinder:
    """
    识别收缩/扩张楔形，并检测突破。

    原文 Wedge Pop Identification：
        - Price bounces from low, consolidates in contracting Wedge
        - Price breaks Wedge upper bound AND crosses above 10/20 EMA
    """

    def __init__(self, lookback: int = 20, convergence_threshold: float = 0.7):
        """
        参数：
            lookback: 向前检查的天数
            convergence_threshold: 收敛程度阈值（0-1），越高越严格
        """
        self.lookback = lookback
        self.convergence_threshold = convergence_threshold

    def _get_prev_day_row(self, df: pd.DataFrame) -> pd.Series | None:
        """
        获取前一天的正确bar（修复双bar股票问题）。
        yfinance每天返回两个bar（05:00和14:30 UTC），
        iloc[-2]可能取到当天盘前而非前一天收盘bar。
        """
        if len(df) < 2:
            return None
        current_idx = df.index[-1]
        prev_day = current_idx.normalize() - pd.Timedelta(days=1)
        mask = df.index.normalize() == prev_day
        matches = df[mask]
        if len(matches) > 0:
            return matches.iloc[-1]
        return df.iloc[-2]

    def find_wedge(self, df: pd.DataFrame) -> WedgeResult | None:
        """
        在最近 N 天数据中查找楔形形态。

        返回：
            WedgeResult 或 None（未找到楔形）
        """
        if len(df) < self.lookback:
            return None

        recent = df.iloc[-self.lookback:]

        highs = recent["high"].values
        lows = recent["low"].values
        closes = recent["close"].values

        # 分段计算高低点趋势
        mid = len(highs) // 3
        first_third = highs[:mid]
        second_third = highs[mid:2*mid]
        last_third = highs[2*mid:]

        first_high_avg = np.mean(first_third)
        second_high_avg = np.mean(second_third)
        last_high_avg = np.mean(last_third)

        first_low_avg = np.mean(lows[:mid])
        second_low_avg = np.mean(lows[mid:2*mid])
        last_low_avg = np.mean(lows[2*mid:])

        # 判断楔形类型
        # 收缩：高点和低点都收敛（后段比前段更靠近中轴）
        high_converging = last_high_avg < second_high_avg < first_high_avg
        low_converging = last_low_avg > second_low_avg > first_low_avg

        # 扩张：高点和低点都发散
        high_expanding = last_high_avg > second_high_avg > first_high_avg
        low_expanding = last_low_avg < second_low_avg < first_low_avg

        if high_converging and low_converging:
            wedge_type = WedgeType.CONTRACTING
        elif high_expanding and low_expanding:
            wedge_type = WedgeType.EXPANDING
        else:
            return None

        # 计算楔形边界（简单实现：取最高/最低点）
        upper_bound = float(np.max(highs))
        lower_bound = float(np.min(lows))

        # 当前价格
        current_price = float(df["close"].iloc[-1])
        today_low = float(df["low"].iloc[-1])

        # 检测突破
        breakout_detected = False
        breakout_direction = None

        if wedge_type == WedgeType.CONTRACTING:
            # 向上突破上轨
            if closes[-1] > upper_bound:
                breakout_detected = True
                breakout_direction = "up"
        elif wedge_type == WedgeType.EXPANDING:
            # 向下突破下轨
            if closes[-1] < lower_bound:
                breakout_detected = True
                breakout_direction = "down"

        return WedgeResult(
            wedge_type=wedge_type,
            upper_bound=upper_bound,
            lower_bound=lower_bound,
            breakout_detected=breakout_detected,
            breakout_direction=breakout_direction,
            breakout_day_low=today_low if breakout_detected and breakout_direction == "up" else 0.0,
        )

    def is_wedge_pop(self, df: pd.DataFrame, ema10: float, ema20: float) -> bool:
        """
        综合判断是否是 Wedge Pop 买入信号。

        原文 Wedge Pop Entry Rules：
        - Enter at Wedge Pivot Point breakout
        - Initial position: 15% of account
        - Stop: Below breakout day closing low
        """
        wedge = self.find_wedge(df)
        if wedge is None:
            return False

        current = float(df["close"].iloc[-1])

        # 必须是收缩楔形向上突破
        if not (wedge.wedge_type == WedgeType.CONTRACTING and wedge.breakout_direction == "up"):
            return False

        # 必须站上 EMA
        if not (current > ema10 and current > ema20):
            return False

        # 成交量检查已移除（IEX 只占全市场成交量的一部分，占比稳定时相对变化仍有效，
        # 但不再作为触发信号的硬性约束）

    def get_breakout_stop(self, df: pd.DataFrame) -> float:
        """
        获取 Wedge Pop 的止损价。

        原文（Page 13, 20, 25）：Stop: Below breakout day low

        实现：突破日的最低价（backtest中用当天actual low，
        live中用昨天low作为当天breakout low的估计）。
        """
        if len(df) < 2:
            return 0.0
        # 用昨天的最低价作为"breakout day low"的估计
        # (live交易时今天的数据还未确定，用昨天作为代理)
        # 使用_get_prev_day_row修复双bar股票问题
        prev_row = self._get_prev_day_row(df)
        yesterday_low = float(prev_row["low"])
        return yesterday_low