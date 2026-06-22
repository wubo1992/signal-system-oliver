"""
signals/watchlist_scanner.py — Watchlist 候选股扫描器

扫描 universe 中处于两种状态的股票：
    1. Reversal Extension：价格远低于 EMA（-20%+），出现恐慌性抛售
       → 观察池：等待 Wedge Pop 确认
    2. Base Tightening：价格高于 EMA20，波动率收缩，尚未突破
       → 观察池：等待 Base n' Break

这些不是买入信号，而是需要持续关注的候选股。
"""

from datetime import datetime
from typing import Any

import pandas as pd

from events import SignalEvent


def scan_watchlist(
    market_data: dict[str, pd.DataFrame],
    date: datetime,
) -> list[SignalEvent]:
    """
    扫描 watchlist 候选股。

    参数：
        market_data: symbol -> DataFrame（含 close, volume 列）
        date: 当前日期

    返回：
        SignalEvent 列表，direction="watch"
    """
    signals: list[SignalEvent] = []
    queue: list[Any] = []  # placeholder, not used for watchlist

    for symbol, df in market_data.items():
        if symbol in ("SPY", "^VIX", "QQQ", "SPX", "VIX"):
            continue

        if df.empty or len(df) < 30:
            continue

        df_to_date = _slice_to_date(df, date)
        if df_to_date.empty or len(df_to_date) < 30:
            continue

        close = float(df_to_date["close"].iloc[-1])
        ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
        ema20 = float(df_to_date["close"].ewm(span=20).mean().iloc[-1])

        if ema20 <= 0:
            continue

        # === 过滤价格门槛 ===
        if close < 10:
            continue

        # === 过滤成交量 ===
        avg_volume = float(df_to_date["volume"].iloc[-20:].mean())
        if avg_volume < 500_000:
            continue

        # === 1. Reversal Extension 检测 ===
        # 价格远低于 EMA20（-20% 以上），可能处于 capitulation
        distance_from_ema20 = (close - ema20) / ema20 * 100

        if distance_from_ema20 < -20:
            # 检查是否有 capitulation 特征：大量抛售
            vol_today = float(df_to_date["volume"].iloc[-1])
            vol_avg = float(df_to_date["volume"].iloc[-21:-1].mean())
            vol_ratio = vol_today / vol_avg if vol_avg > 0 else 0

            # 大幅下跌且放量 = capitulation
            price_change = (close - float(df_to_date["close"].iloc[-2])) / float(df_to_date["close"].iloc[-2]) * 100

            if price_change < -3 and vol_ratio > 1.5:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="watch",
                    strength=3,
                    reason=f"[Reversal Extension] Price {distance_from_ema20:.1f}% below EMA20 | "
                           f"Capitulation: {price_change:.1f}% drop, vol {vol_ratio:.1f}x avg",
                    stop_loss=round(ema20 * 0.95, 2),
                    cycle_stage="reversal_extension",
                    current_price=close,
                )
                signals.append(sig)
                continue

        # === 2. Base Tightening 检测 ===
        # 价格在 EMA20 之上，波动率收缩，尚未突破
        # 条件：
        #   - Price > EMA20
        #   - EMA10 > EMA20（多头排列）
        #   - 过去 10 天波动率 < 5%（收缩）
        #   - 尚未明显突破（close < 20日高点 5% 以内）

        if close > ema20 and ema10 > ema20:
            # 检查波动率收缩
            recent_highs = df_to_date["high"].iloc[-10:]
            recent_lows = df_to_date["low"].iloc[-10:]
            price_range = (recent_highs.max() - recent_lows.min()) / recent_lows.min() * 100

            # 20日高点
            high_20 = float(df_to_date["high"].iloc[-20:].max())

            if price_range < 5 and close < high_20 * 1.05:
                # 处于 base tightening 状态
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="watch",
                    strength=2,
                    reason=f"[Base Tightening] Price {close:.2f} above EMA20 | "
                           f"Range contraction {price_range:.1f}% in 10 days | "
                           f"High 20d: ${high_20:.2f}",
                    stop_loss=round(ema20 * 0.98, 2),
                    cycle_stage="base_tightening",
                    current_price=close,
                )
                signals.append(sig)

    return signals


def _slice_to_date(df: pd.DataFrame, date: datetime) -> pd.DataFrame:
    """切片到指定日期"""
    from datetime import timezone
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize("UTC")
        df = df.copy()
        df.index = idx
    return df[df.index <= date]
