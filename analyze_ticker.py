#!/usr/bin/env python3
"""
analyze_ticker.py — 单股票分析器

使用方法：
    uv run python analyze_ticker.py AAPL
    uv run python analyze_ticker.py "Apple Inc"

功能：
    1. 如果输入是公司名称，搜索对应 ticker
    2. 获取近 6 个月日线数据
    3. 计算 10/20 EMA
    4. 使用 CycleDetector.classify() 获取当前 cycle stage
    5. 计算：价格 vs EMA 距离、成交量趋势、extension 指标
    6. 输出完整的 6-field 分析报告
"""

import sys
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import yfinance as yf
import pandas as pd

from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage


def search_ticker(company_name: str) -> str | None:
    """通过 yfinance 搜索公司名称对应的 ticker。"""
    try:
        ticker = yf.Ticker(company_name)
        info = ticker.info
        if info and "symbol" in info:
            return info["symbol"]
    except Exception:
        pass
    return None


def fetch_data(symbol: str, months: int = 6) -> pd.DataFrame:
    """获取近 N 个月的日线数据。"""
    end_date = datetime.now(tz=timezone.utc)
    start_date = end_date - timedelta(days=months * 30)

    df = yf.download(symbol, start=start_date, end=end_date, progress=False)
    if df.empty:
        raise ValueError(f"无法获取 {symbol} 的数据")

    # 确保 index 是 DatetimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # 兼容 yfinance 多级列名
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 计算 EMA
    df["EMA10"] = df["Close"].ewm(span=10).mean()
    df["EMA20"] = df["Close"].ewm(span=20).mean()

    return df


def analyze_stock(symbol: str, df: pd.DataFrame) -> dict:
    """分析单只股票，返回分析结果字典。"""
    close = float(df["Close"].iloc[-1])
    ema10 = float(df["EMA10"].iloc[-1])
    ema20 = float(df["EMA20"].iloc[-1])

    # 获取上一个收盘价
    if len(df) >= 2:
        prev_close = float(df["Close"].iloc[-2])
    else:
        prev_close = close

    # Cycle Stage
    detector = CycleDetector()
    stage = detector.classify(df)

    # 价格变化
    price_change = (close - prev_close) / prev_close * 100

    # EMA 距离
    ema10_distance = (close - ema10) / ema10 * 100
    ema20_distance = (close - ema20) / ema20 * 100

    # 成交量
    vol_today = float(df["Volume"].iloc[-1])
    vol_avg_20 = float(df["Volume"].iloc[-21:-1].mean()) if len(df) >= 21 else vol_today
    vol_ratio = vol_today / vol_avg_20 if vol_avg_20 > 0 else 0

    # 20日高点/低点
    high_20 = float(df["High"].iloc[-20:].max())
    low_20 = float(df["Low"].iloc[-20:].min())

    # 距 20 日高低点
    dist_high = (close - high_20) / high_20 * 100
    dist_low = (close - low_20) / low_20 * 100

    # 10 日波动率
    returns_10 = df["Close"].iloc[-10:].pct_change().dropna()
    volatility_10 = float(returns_10.std() * (252 ** 0.5) * 100) if len(returns_10) >= 2 else 0

    # Extension 状态
    is_extended = close > ema10 * 1.10
    extension_pct = (close - ema10) / ema10 * 100 if ema10 > 0 else 0

    # 多头排列
    is_perfect_stack = close > ema10 > ema20 and ema10 > ema20

    # 成交量趋势（10日平均）
    vol_sma_10 = float(df["Volume"].iloc[-10:].mean())

    # 置信度（基于多个因素）
    confidence = _calculate_confidence(
        stage=stage,
        close=close,
        ema10=ema10,
        ema20=ema20,
        ema10_distance=ema10_distance,
        vol_ratio=vol_ratio,
        is_perfect_stack=is_perfect_stack,
    )

    return {
        "symbol": symbol,
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": close,
        "ema10": ema10,
        "ema20": ema20,
        "stage": stage,
        "stage_name": stage.value,
        "price_change": price_change,
        "ema10_distance": ema10_distance,
        "ema20_distance": ema20_distance,
        "vol_today": vol_today,
        "vol_avg_20": vol_avg_20,
        "vol_ratio": vol_ratio,
        "high_20": high_20,
        "low_20": low_20,
        "dist_high": dist_high,
        "dist_low": dist_low,
        "volatility_10": volatility_10,
        "is_extended": is_extended,
        "extension_pct": extension_pct,
        "is_perfect_stack": is_perfect_stack,
        "confidence": confidence,
        "df": df,  # 保留原始数据用于图表
    }


def _calculate_confidence(
    stage: CycleStage,
    close: float,
    ema10: float,
    ema20: float,
    ema10_distance: float,
    vol_ratio: float,
    is_perfect_stack: bool,
) -> float:
    """计算信号置信度（0-100%）。"""
    score = 50.0  # 基础分

    # Stage 加分
    if stage == CycleStage.WEDGE_POP:
        score += 20
    elif stage == CycleStage.EMA_CROSSBACK:
        score += 15
    elif stage == CycleStage.BASE_N_BREAK:
        score += 10
    elif stage == CycleStage.REVERSAL_EXTENSION:
        score -= 10
    elif stage == CycleStage.WEDGE_DROP:
        score -= 20

    # 价格强度
    if close > ema10:
        score += 10
    if is_perfect_stack:
        score += 10

    # 成交量确认
    if vol_ratio > 1.5:
        score += 10
    elif vol_ratio > 1.2:
        score += 5

    # EMA 距离（不要过度延伸）
    if -5 < ema10_distance < 10:
        score += 5

    # 限制范围
    return max(0, min(100, score))


def format_report(analysis: dict) -> str:
    """格式化分析报告。"""
    lines: list[str] = []

    symbol = analysis["symbol"]
    date = analysis["date"]
    close = analysis["close"]
    ema10 = analysis["ema10"]
    ema20 = analysis["ema20"]
    stage = analysis["stage_name"]
    confidence = analysis["confidence"]

    # 计算趋势状态
    trend_status = _get_trend_status(analysis)

    # ── 标题 ──────────────────────────────────────
    lines.append("=" * 60)
    lines.append(f"  Oliver Kell 单股票分析报告 — {symbol}")
    lines.append(f"  分析日期：{date}")
    lines.append("=" * 60)
    lines.append("")

    # ── Field 1: 当前价格 & 趋势状态 ─────────────
    lines.append("【1. 当前价格 & 趋势状态】")
    lines.append("")
    lines.append(f"  当前价格：${close:.2f}")
    lines.append(f"  10 EMA：  ${ema10:.2f}  （{'高于' if close > ema10 else '低于'}价格，{analysis['ema10_distance']:+.1f}%）")
    lines.append(f"  20 EMA：  ${ema20:.2f}  （{'高于' if close > ema20 else '低于'}价格，{analysis['ema20_distance']:+.1f}%）")
    lines.append(f"  趋势状态：{trend_status}")
    lines.append("")

    # ── Field 2: Cycle Stage & 置信度 ────────────
    stage_display = {
        "wedge_pop": "🟢 Wedge Pop — 最佳买点",
        "ema_crossback": "🔵 EMA Crossback — 回踩入场",
        "base_n_break": "🔵 Base n' Break — 突破确认",
        "exhaustion_extension": "🟡 Exhaustion Extension — 顶部警告",
        "wedge_drop": "🔴 Wedge Drop — 下降确认",
        "reversal_extension": "🟠 Reversal Extension — 底部恐慌",
        "unknown": "⚪ Unknown",
    }

    lines.append("【2. Cycle Stage & 置信度】")
    lines.append("")
    lines.append(f"  当前阶段：{stage_display.get(stage, stage)}")
    lines.append(f"  置信度：  {confidence:.0f}%")
    lines.append("")

    # ── Field 3: 图表证据 & 推理 ─────────────────
    lines.append("【3. 图表证据 & 推理】")
    lines.append("")
    lines.append(f"  20日高点：${analysis['high_20']:.2f}  （当前价格距高点 {analysis['dist_high']:.1f}%）")
    lines.append(f"  20日低点：${analysis['low_20']:.2f}  （当前价格距低点 {analysis['dist_low']:+.1f}%）")
    lines.append(f"  10日波动率：{analysis['volatility_10']:.1f}%")

    if analysis["is_extended"]:
        lines.append(f"  Extension：价格超出 EMA10 {analysis['extension_pct']:.1f}%（偏延伸，谨慎追高）")
    else:
        lines.append(f"  Extension：价格低于 EMA10，未延伸")

    if analysis["is_perfect_stack"]:
        lines.append("  多头排列：✅ Price > EMA10 > EMA20")

    # 成交量
    vol_today_m = analysis["vol_today"] / 1_000_000
    vol_avg_m = analysis["vol_avg_20"] / 1_000_000
    lines.append(f"  成交量：  今日 {vol_today_m:.1f}M / 20日均量 {vol_avg_m:.1f}M （{analysis['vol_ratio']:.1f}x）")

    lines.append("")

    # ── Field 4: 操作建议 ────────────────────────
    lines.append("【4. 操作建议】")
    lines.append("")
    action = _get_action_recommendation(analysis)
    lines.append(f"  {action}")
    lines.append("")

    # ── 信号摘要 ─────────────────────────────────
    lines.append("-" * 60)
    lines.append("信号摘要")
    lines.append("-" * 60)

    summary = _get_signal_summary(analysis)
    lines.append(f"  方向：{summary['direction']}")
    lines.append(f"  强度：{summary['strength']}")
    lines.append(f"  止损：{summary['stop_loss']}")
    lines.append(f"  入场理由：{summary['reason']}")
    lines.append("")

    return "\n".join(lines)


def _get_trend_status(analysis: dict) -> str:
    """判断趋势状态。"""
    if analysis["is_perfect_stack"]:
        return "多头排列（强势）"
    elif analysis["close"] > analysis["ema20"]:
        return "价格在 EMA20 之上（偏强）"
    elif analysis["close"] > analysis["ema10"]:
        return "价格在 EMA10 和 EMA20 之间"
    else:
        return "价格在 EMA10 之下（偏弱）"


def _get_action_recommendation(analysis: dict) -> str:
    """根据分析结果给出操作建议。"""
    stage = analysis["stage_name"]

    if stage == "wedge_pop":
        return (
            "✅ 买入机会 — Wedge Pop 是最佳买点\n"
            "   建议：30%仓位，等待价格突破楔形上轨后买入\n"
            "   止损：楔形下轨以下 1-2%"
        )
    elif stage == "ema_crossback":
        return (
            "🔵 回踩买入 — EMA Crossback 是良好入场点\n"
            "   建议：等待价格确认站稳 EMA10/20 后买入\n"
            "   止损：回踩日最低价以下 1-2%"
        )
    elif stage == "base_n_break":
        return (
            "🔵 盘整突破 — Base n' Break 确认趋势延续\n"
            "   建议：价格突破盘整区间后买入\n"
            "   止损：盘整区间低点以下 2%"
        )
    elif stage == "exhaustion_extension":
        return (
            "🟡 警惕延伸 — Exhaustion Extension 区域\n"
            "   建议：持有的可继续持有，不建议新买入\n"
            "   注意观察是否有 Wedge Pop 迹象"
        )
    elif stage == "wedge_drop":
        return (
            "🔴 离场观望 — Wedge Drop 确认下降趋势\n"
            "   建议：全部卖出，等待 Reversal Extension 信号\n"
            "   避免：任何买入操作"
        )
    elif stage == "reversal_extension":
        return (
            "🟠 底部观察 — Reversal Extension 显示恐慌\n"
            "   建议：不买入，等待 Wedge Pop 确认\n"
            "   关注：成交量是否萎缩，价格是否企稳"
        )
    else:
        return (
            "⚪ 观望 — 当前无明确信号\n"
            "   建议：等待市场给出明确方向\n"
            "   关注：Wedge Pop 或 EMA Crossback 信号"
        )


def _get_signal_summary(analysis: dict) -> dict:
    """生成信号摘要。"""
    stage = analysis["stage_name"]

    if stage in ("wedge_pop", "ema_crossback", "base_n_break"):
        direction = "买入"
        if stage == "wedge_pop":
            strength = "★★★★★（最强）"
            reason = f"{stage} 信号，等待楔形突破确认"
        elif stage == "ema_crossback":
            strength = "★★★★☆（强）"
            reason = f"{stage} 信号，价格回踩 EMA 确认"
        else:
            strength = "★★★☆☆（中等）"
            reason = f"{stage} 信号，价格突破盘整区间"
    elif stage == "exhaustion_extension":
        direction = "观望"
        strength = "★★★☆☆"
        reason = "延伸末期，不宜新买入"
    elif stage == "wedge_drop":
        direction = "卖出/离场"
        strength = "★★★★★"
        reason = "下降趋势确认，等待新周期"
    elif stage == "reversal_extension":
        direction = "观察"
        strength = "★★☆☆☆"
        reason = "底部恐慌区域，等待 Wedge Pop"
    else:
        direction = "观望"
        strength = "—"
        reason = "无明确信号"

    # 止损
    if direction == "买入":
        stop_loss = f"${analysis['ema20'] * 0.98:.2f}（EMA20 以下 2%）"
    else:
        stop_loss = "—"

    return {
        "direction": direction,
        "strength": strength,
        "stop_loss": stop_loss,
        "reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Oliver Kell 单股票分析器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  uv run python analyze_ticker.py AAPL
  uv run python analyze_ticker.py "Apple Inc"
  uv run python analyze_ticker.py TSLA --months 12
        """,
    )
    parser.add_argument(
        "symbol",
        help="股票代码（如 AAPL）或公司名称（如 'Apple Inc'）",
    )
    parser.add_argument(
        "--months",
        type=int,
        default=6,
        dest="months",
        help="获取数据月数（默认 6 个月）",
    )

    args = parser.parse_args()

    symbol_input = args.symbol.strip()
    months = args.months

    # 如果输入包含空格，尝试作为公司名搜索
    symbol = symbol_input.upper()
    if " " in symbol_input and not symbol_input.isupper():
        print(f"正在搜索公司 '{symbol_input}' 对应的 ticker...")
        found = search_ticker(symbol_input)
        if found:
            symbol = found.upper()
            print(f"找到：{symbol}")
        else:
            print(f"未找到 '{symbol_input}'，尝试直接作为 ticker 使用...")
    else:
        # 验证 ticker 是否有效
        try:
            test_df = yf.download(symbol, period="5d", progress=False)
            if test_df.empty:
                print(f"[警告] 无法获取 {symbol} 的数据，可能 ticker 无效")
        except Exception as e:
            print(f"[警告] 验证 {symbol} 时出错：{e}")

    print(f"\n正在获取 {symbol} 近 {months} 个月的数据...")
    try:
        df = fetch_data(symbol, months=months)
        print(f"成功获取 {len(df)} 个交易日的数据")
    except ValueError as e:
        print(f"[错误] {e}")
        sys.exit(1)

    print("\n正在分析...")
    analysis = analyze_stock(symbol, df)

    # 输出报告
    report = format_report(analysis)
    print("\n" + report)


if __name__ == "__main__":
    main()
