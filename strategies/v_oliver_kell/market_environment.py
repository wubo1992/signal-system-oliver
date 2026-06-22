"""
strategies/v_oliver_kell/market_environment.py

市场环境四档分类（原文 Section 6.1）：
    Quality:   Index above 20 EMA, multiple leaders following
    Average:   Index oscillating near 20 EMA
    Poor:      Index below 20 EMA, unable to profit
    Hostile:   Systematic decline
"""

from enum import Enum

import pandas as pd


class MarketState(Enum):
    QUALITY = "quality"
    AVERAGE = "average"
    POOR = "poor"
    HOSTILE = "hostile"


class MarketEnvironment:
    """
    根据指数（QQQ/SPY）与 20 EMA 的关系判断市场环境。

    原文四档：
        Quality:  指数 > 20 EMA → 6-7核心持仓，可融资
        Average:  指数在 20 EMA 附近振荡 → 3-5持仓，现金为王
        Poor:     指数 < 20 EMA，无法盈利 → 1-2持仓，最多30%仓位
        Hostile:  指数持续下跌 → 全现金，等待观察
    """

    # 接近 EMA 的阈值（百分比）
    NEAR_THRESHOLD = 0.01  # 1%

    def __init__(self, index_symbol: str = "QQQ"):
        self.index_symbol = index_symbol

    def classify(self, index_df: pd.DataFrame) -> MarketState:
        """
        根据指数数据判断市场环境。

        参数：
            index_df: 含 close 和 EMA20 列的 DataFrame

        返回：
            MarketState 枚举值
        """
        if len(index_df) < 20:
            return MarketState.HOSTILE

        current_price = float(index_df["close"].iloc[-1])

        # Compute EMA20 inline if not present in DataFrame
        if "EMA20" in index_df.columns:
            ema20 = float(index_df["EMA20"].iloc[-1])
        else:
            ema20 = float(index_df["close"].ewm(span=20).mean().iloc[-1])

        # 检查趋势：持续下跌 = Hostile
        if self._is_systematic_decline(index_df):
            return MarketState.HOSTILE

        # 分类
        if current_price > ema20 * (1 + self.NEAR_THRESHOLD):
            return MarketState.QUALITY
        elif current_price < ema20 * (1 - self.NEAR_THRESHOLD):
            return MarketState.POOR
        else:
            return MarketState.AVERAGE

    def _is_systematic_decline(self, df: pd.DataFrame, lookback: int = 10) -> bool:
        """
        检查是否持续下跌（Hostile）。

        原文：Systematic decline → Hostile
        实现：过去 lookback 天中至少有 8 天收盘价低于前一日
        """
        if len(df) < lookback + 1:
            return False
        declines = 0
        for i in range(-lookback, 0):
            if df["close"].iloc[i] < df["close"].iloc[i - 1]:
                declines += 1
        return declines >= int(lookback * 0.8)

    def max_position_pct(self, state: MarketState) -> float:
        """
        根据市场状态返回最大仓位限制（原文 Table）。

        Quality:   ~190% (margin OK)
        Average:   50% (3-5 positions, cash-heavy)
        Poor:      30% (1-2 positions, max 30%)
        Hostile:   0%  (all cash)
        """
        mapping = {
            MarketState.QUALITY: 1.9,
            MarketState.AVERAGE: 0.5,
            MarketState.POOR: 0.3,
            MarketState.HOSTILE: 0.0,
        }
        return mapping.get(state, 0.0)