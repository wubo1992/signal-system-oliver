"""
signals/watchlist_scanner.py — Watchlist 候选股扫描器

扫描 universe 中处于两种状态的股票：
    1. Reversal Extension：最近20个交易日内曾低于 EMA20 10% 以上，今天出现反弹
       → 观察池：等待 Wedge Pop 确认
    2. Base Tightening：价格高于 EMA20，波动率收缩，尚未突破
       → 观察池：等待 Base n' Break

这些不是买入信号，而是需要持续关注的候选股。
"""

from datetime import datetime
from typing import Any

import pandas as pd

from events import SignalEvent
from strategies.v_oliver_kell.weinstein_stage import compute_weinstein_detail


def scan_watchlist(
    market_data: dict[str, pd.DataFrame],
    date: datetime,
    oneil_rs_map: dict[str, tuple[int | None, float | None]] | None = None,
) -> list[SignalEvent]:
    """
    扫描 watchlist 候选股。

    参数：
        market_data: symbol -> DataFrame（含 close, volume 列）
        date: 当前日期
        oneil_rs_map: symbol -> (RS 评级, RS 倍数)，由 oneil_rs.compute_oneil_rs_map 预先算好

    返回：
        SignalEvent 列表，direction="watch"
    """
    oneil_rs_map = oneil_rs_map or {}
    signals: list[SignalEvent] = []
    queue: list[Any] = []  # placeholder, not used for watchlist

    # 拉取 SPY 作为 RS 基准（兼容缺失场景）
    benchmark_df = market_data.get("SPY", pd.DataFrame()).copy()

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

        # === 过滤成交额 ===
        # 用美元成交额而不是成交股数，避免高价股（如 SNDK）被误判为流动性不足。
        avg_volume = float(df_to_date["volume"].iloc[-20:].mean())
        avg_dollar_volume = close * avg_volume
        if avg_dollar_volume < 5_000_000:
            continue

        # === 1. Reversal Extension 检测 ===
        # 三条件并存：
        #   1) 过去 20 天内 EMA20 距离曾 ≤ -10%（股票曾深度超卖，-10% 是起点不是终点）
        #   2) 累计反弹 ≥ 10%（从 lookback 内底部最低收盘价到现在，反弹幅度足够大；
        #                   可以是若干个交易日的累计，单日 10%+ 也算达成）
        #   3) 当日单日反弹 ≥ 3%（避免纯慢反弹但当日无动作的票，确保今日有真实买盘）
        ema20_history = df_to_date["close"].ewm(span=20).mean()
        recent_closes = df_to_date["close"].iloc[-20:]
        recent_ema20 = ema20_history.iloc[-20:]
        recent_distances = (recent_closes - recent_ema20) / recent_ema20 * 100
        recent_min_distance = float(recent_distances.min())

        # 底部 = lookback 内最低收盘价
        bottom_close = float(recent_closes.min())
        bottom_idx = recent_closes.idxmin()
        days_since_bottom = int((df_to_date.index[-1] - bottom_idx).days)

        # 累计反弹幅度（核心条件）
        cumulative_rebound = (close - bottom_close) / bottom_close * 100

        distance_from_ema20 = (close - ema20) / ema20 * 100
        price_change = (close - float(df_to_date["close"].iloc[-2])) / float(df_to_date["close"].iloc[-2]) * 100

        if recent_min_distance <= -10 and cumulative_rebound >= 10.0 and price_change >= 3.0:
            # 计算成交量比用于 reason 描述（非触发条件）
            vol_today = float(df_to_date["volume"].iloc[-1])
            vol_avg = float(df_to_date["volume"].iloc[-21:-1].mean())
            vol_ratio = vol_today / vol_avg if vol_avg > 0 else 0
            rs_value = _compute_rs_value(df_to_date, benchmark_df)
            rs_value_10d = _compute_rs_value_short(df_to_date, benchmark_df, lookback=10)
            rs_value_10w = _compute_rs_value_long(df_to_date, benchmark_df, lookback=50)
            rs_rating, rs_ratio = oneil_rs_map.get(symbol, (None, None))
            stage_detail = compute_weinstein_detail(df_to_date, as_of=date)
            stage = stage_detail["stage"] if stage_detail else None
            stage_label = stage_detail["label"] if stage_detail else "—"

            sig = SignalEvent.create(
                symbol=symbol,
                timestamp=date,
                direction="watch",
                strength=3,
                reason=f"[Reversal Extension] Current EMA20 distance: {distance_from_ema20:+.1f}% | "
                       f"Recent 20d low: {recent_min_distance:.1f}% | "
                       f"Cum rebound (since bottom {days_since_bottom}d ago): +{cumulative_rebound:.1f}% | "
                       f"Today: +{price_change:.1f}%, vol {vol_ratio:.1f}x avg"
                       f"{_rs_short_token(rs_value_10d)}{_rs_token(rs_value)}{_rs_long_token(rs_value_10w)}"
                       f"{_oneil_rs_token(rs_rating, rs_ratio)}"
                       f"{_stage_token(stage, stage_label, bool(stage_detail and stage_detail.get('is_developing')))}",
                stop_loss=round(ema20 * 0.95, 2),
                cycle_stage="reversal_extension",
                current_price=close,
            )
            sig.data["rs_value_10d"] = rs_value_10d
            sig.data["rs_value"] = rs_value
            sig.data["rs_value_10w"] = rs_value_10w
            sig.data["volume_ratio"] = vol_ratio if vol_avg > 0 else None
            sig.data["rs_rating"] = rs_rating
            sig.data["rs_ratio"] = rs_ratio
            sig.data["weinstein_stage"] = stage_label
            sig.data["weinstein_stage_num"] = stage
            if stage_detail:
                sig.data["weinstein_substage"] = stage_detail.get("substage")
                sig.data["weinstein_substage_label"] = stage_detail.get("substage_label")
                sig.data["weinstein_ma30_slope"] = stage_detail.get("ma30_slope_pct")
                sig.data["weinstein_price_vs_ma"] = stage_detail.get("price_vs_ma_pct")
                sig.data["weinstein_weeks_in_stage"] = stage_detail.get("duration_weeks")
                sig.data["weinstein_developing"] = stage_detail.get("is_developing")
                sig.data["weinstein_confirmed_label"] = stage_detail.get("confirmed_label")
                sig.data["weinstein_week_status"] = stage_detail.get("week_status")
            signals.append(sig)
            continue


        # === 2. Base Tightening 检测 ===
        # 价格在 EMA20 之上，波动率收缩，尚未突破
        # 条件：
        #   - Price > EMA20
        #   - EMA10 > EMA20（多头排列）
        #   - 过去 10 天波动率 < 7%（收紧中或已完成；放宽自 5% 以捕获更多候选）
        #   - 尚未明显突破（close < 20日高点 5% 以内）

        if close > ema20 and ema10 > ema20:
            # 检查波动率收缩
            recent_highs = df_to_date["high"].iloc[-10:]
            recent_lows = df_to_date["low"].iloc[-10:]
            price_range = (recent_highs.max() - recent_lows.min()) / recent_lows.min() * 100

            # 20日高点
            high_20 = float(df_to_date["high"].iloc[-20:].max())

            if price_range < 7 and close < high_20 * 1.05:
                # 量比 + RS 数值（用于 reason 与 data）
                vol_today = float(df_to_date["volume"].iloc[-1])
                vol_avg_20 = float(df_to_date["volume"].iloc[-21:-1].mean())
                vol_ratio = vol_today / vol_avg_20 if vol_avg_20 > 0 else 0
                rs_value = _compute_rs_value(df_to_date, benchmark_df)
                rs_value_10d = _compute_rs_value_short(df_to_date, benchmark_df, lookback=10)
                rs_value_10w = _compute_rs_value_long(df_to_date, benchmark_df, lookback=50)
                rs_rating, rs_ratio = oneil_rs_map.get(symbol, (None, None))
                stage_detail = compute_weinstein_detail(df_to_date, as_of=date)
                stage = stage_detail["stage"] if stage_detail else None
                stage_label = stage_detail["label"] if stage_detail else "—"

                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="watch",
                    strength=2,
                    reason=f"[Base Tightening] Price {close:.2f} above EMA20 | "
                           f"Range contraction {price_range:.1f}% in 10 days | "
                           f"High 20d: ${high_20:.2f}"
                           f"{_rs_short_token(rs_value_10d)}{_rs_token(rs_value)}{_rs_long_token(rs_value_10w)}{_vol_token(vol_ratio if vol_avg_20 > 0 else None)}"
                           f"{_oneil_rs_token(rs_rating, rs_ratio)}"
                           f"{_stage_token(stage, stage_label, bool(stage_detail and stage_detail.get('is_developing')))}",
                    stop_loss=round(ema20 * 0.98, 2),
                    cycle_stage="base_tightening",
                    current_price=close,
                )
                sig.data["rs_value_10d"] = rs_value_10d
                sig.data["rs_value"] = rs_value
                sig.data["rs_value_10w"] = rs_value_10w
                sig.data["volume_ratio"] = vol_ratio if vol_avg_20 > 0 else None
                sig.data["rs_rating"] = rs_rating
                sig.data["rs_ratio"] = rs_ratio
                sig.data["weinstein_stage"] = stage_label
                sig.data["weinstein_stage_num"] = stage
                if stage_detail:
                    sig.data["weinstein_substage"] = stage_detail.get("substage")
                    sig.data["weinstein_substage_label"] = stage_detail.get("substage_label")
                    sig.data["weinstein_ma30_slope"] = stage_detail.get("ma30_slope_pct")
                    sig.data["weinstein_price_vs_ma"] = stage_detail.get("price_vs_ma_pct")
                    sig.data["weinstein_weeks_in_stage"] = stage_detail.get("duration_weeks")
                    sig.data["weinstein_developing"] = stage_detail.get("is_developing")
                    sig.data["weinstein_confirmed_label"] = stage_detail.get("confirmed_label")
                    sig.data["weinstein_week_status"] = stage_detail.get("week_status")
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


def _compute_rs_value(df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 20) -> float | None:
    """计算 RS 数值（倍数形式）：过去 N 个交易日个股涨幅 / 大盘涨幅。基准缺失或数据不足返回 None。

    公式：RS = (stock_today / stock_Nd_ago) / (bench_today / bench_Nd_ago)
          RS = 1.0 表示与大盘同步，RS > 1.0 表示跑赢，RS < 1.0 表示跑输
    """
    if benchmark.empty or len(benchmark) < lookback + 5 or len(df) < lookback + 5:
        return None
    try:
        aligned_df, aligned_bench = df.align(benchmark, join="inner")
        if aligned_df.empty or aligned_bench.empty or len(aligned_df) < lookback + 1:
            return None
        stock_close = aligned_df["close"]
        bench_close = aligned_bench["close"]
        stock_close_n_ago = stock_close.shift(lookback)
        bench_close_n_ago = bench_close.shift(lookback)
        stock_gain = stock_close / stock_close_n_ago
        bench_gain = bench_close / bench_close_n_ago
        rs = stock_gain / bench_gain
        if rs.empty:
            return None
        rs_last = float(rs.iloc[-1])
        # NaN / inf 兜底
        import math
        if math.isnan(rs_last) or math.isinf(rs_last):
            return None
        return rs_last
    except Exception:
        return None


def _compute_rs_value_short(df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 10) -> float | None:
    """计算短期 RS（默认 10 个交易日 ≈ 2 周）。"""
    return _compute_rs_value(df, benchmark, lookback=lookback)


def _compute_rs_value_long(df: pd.DataFrame, benchmark: pd.DataFrame, lookback: int = 50) -> float | None:
    """计算长周期 RS（默认 10 周 = 50 个交易日）。"""
    return _compute_rs_value(df, benchmark, lookback=lookback)


def _rs_token(rs_value: float | None) -> str:
    if rs_value is None:
        return ""
    try:
        return f" | [RS] {rs_value:.4f}"
    except Exception:
        return ""


def _rs_short_token(rs_value: float | None) -> str:
    if rs_value is None:
        return ""
    try:
        return f" | [RS-10D] {rs_value:.4f}"
    except Exception:
        return ""


def _rs_long_token(rs_value: float | None) -> str:
    if rs_value is None:
        return ""
    try:
        return f" | [RS-10W] {rs_value:.4f}"
    except Exception:
        return ""


def _stage_token(stage: int | None, label: str, developing: bool = False) -> str:
    """Weinstein 阶段 token（[WStage] Stage 2 上升 · 2A 上升初期）。数据不足时返回空串。"""
    if stage is None:
        return ""
    flag = "（发展中）" if developing else ""
    return f" | [WStage] {label}{flag}"


def _oneil_rs_token(rs_rating: int | None, rs_ratio: float | None) -> str:
    """O'Neil RS 评级 token（[RS-Rating] 1-99 百分位 + [RS-Mult] SPY 倍数）。"""

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


def _vol_token(vol_ratio: float | None) -> str:
    if vol_ratio is None:
        return ""
    try:
        return f" | [Vol] {vol_ratio:.1f}x"
    except Exception:
        return ""
