"""
2020-2026年Wedge Pop回测：AMZN和KLAC
"""

import sys
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from data.fetcher import fetch
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage


def load_data_for_symbols(symbols: list, start_date: str = "2020-01-01") -> dict:
    """加载多只股票数据"""
    end_date = datetime(2026, 5, 22, tzinfo=timezone.utc)
    data = fetch(symbols, history_days=2500, live_mode=False, end_date=end_date)
    return data


def slice_to_date(df: pd.DataFrame, date: datetime) -> pd.DataFrame:
    """切片到指定日期"""
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize("UTC")
        df = df.copy()
        df.index = idx
    return df[df.index < date + pd.Timedelta(days=1)]


def find_wedge_pop_signals(df: pd.DataFrame, symbol: str) -> list:
    """找所有Wedge Pop信号"""
    signals = []
    detector = CycleDetector()

    # 从2020年开始
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    df_2020 = df[df.index >= start].copy()

    if len(df_2020) < 30:
        return signals

    dates = df_2020.index.tolist()

    for i, date in enumerate(dates):
        if i < 25:
            continue

        df_to_date = slice_to_date(df, date)
        if len(df_to_date) < 30:
            continue

        try:
            stage = detector.classify(df_to_date)

            if stage == CycleStage.WEDGE_POP:
                row = df[df.index < date + pd.Timedelta(days=1)].iloc[-1]
                signals.append({
                    "date": date,
                    "symbol": symbol,
                    "signal_type": "Wedge Pop",
                    "price": row["close"],
                    "idx": df.index.get_loc(date)
                })
        except Exception as e:
            continue

    return signals


def calculate_returns(df: pd.DataFrame, signal_idx: int, holding_days: list) -> dict:
    """计算信号后1/5/10/20日的收益率"""
    returns = {}
    buy_price = df.iloc[signal_idx]["close"]

    for days in holding_days:
        if signal_idx + days < len(df):
            sell_price = df.iloc[signal_idx + days]["close"]
            ret = (sell_price - buy_price) / buy_price
            returns[days] = ret
        else:
            returns[days] = None

    return returns


def backtest_signals(symbol: str, data: dict) -> dict:
    """对单只股票Wedge Pop进行回测"""
    if symbol not in data:
        return {"error": f"无数据: {symbol}"}

    df = data[symbol]

    if len(df) < 50:
        return {"error": f"数据不足: {len(df)}天"}

    signals = find_wedge_pop_signals(df, symbol)

    if not signals:
        return {"signal_count": 0, "signals": []}

    holding_days = [1, 5, 10, 20]
    results = []

    for sig in signals:
        idx = sig["idx"]
        returns = calculate_returns(df, idx, holding_days)

        result = {
            "date": sig["date"].strftime("%Y-%m-%d") if hasattr(sig["date"], 'strftime') else str(sig["date"]),
            "price": sig["price"],
        }

        for days in holding_days:
            if returns[days] is not None:
                result[f"ret_{days}d"] = returns[days]
            else:
                result[f"ret_{days}d"] = None

        results.append(result)

    # 汇总统计
    summary = calculate_summary(results, holding_days)

    return {
        "signal_count": len(signals),
        "signals": results,
        "summary": summary
    }


def calculate_summary(results: list, holding_days: list) -> dict:
    """计算汇总统计"""
    summary = {}

    for days in holding_days:
        key = f"ret_{days}d"
        values = [r[key] for r in results if r[key] is not None]

        if values:
            wins = [v for v in values if v > 0]
            summary[days] = {
                "win_rate": len(wins) / len(values) * 100 if values else 0,
                "avg_return": np.mean(values) * 100 if values else 0,
                "count": len(values)
            }
        else:
            summary[days] = {"win_rate": 0, "avg_return": 0, "count": 0}

    return summary


def print_results(symbol: str, result: dict):
    """打印结果"""
    if "error" in result:
        print(f"{symbol}: 错误 - {result['error']}")
        return

    count = result["signal_count"]
    summary = result.get("summary", {})

    print(f"\n{'='*80}")
    print(f"{symbol} — Wedge Pop（共{count}个信号）")
    print(f"{'='*80}")

    if count == 0:
        print("  无Wedge Pop信号")
        return

    # 打印汇总表
    print(f"\n{'持有期':<10} {'胜率':>10} {'平均收益':>12} {'信号数':>8}")
    print("-" * 42)

    for days in [1, 5, 10, 20]:
        if days in summary:
            s = summary[days]
            print(f"{days}日{'':<6} {s['win_rate']:>9.1f}% {s['avg_return']:>11.2f}% {s['count']:>8}")

    # 打印每次信号详情
    print(f"\n{'日期':<12} {'买入价':>10} {'1日':>8} {'5日':>8} {'10日':>8} {'20日':>8}")
    print("-" * 62)

    for r in result["signals"]:
        date = r["date"]
        price = r["price"]
        r1 = f"{r['ret_1d']*100:.2f}%" if r['ret_1d'] is not None else "N/A"
        r5 = f"{r['ret_5d']*100:.2f}%" if r['ret_5d'] is not None else "N/A"
        r10 = f"{r['ret_10d']*100:.2f}%" if r['ret_10d'] is not None else "N/A"
        r20 = f"{r['ret_20d']*100:.2f}%" if r['ret_20d'] is not None else "N/A"

        print(f"{date:<12} {price:>10.2f} {r1:>8} {r5:>8} {r10:>8} {r20:>8}")


if __name__ == "__main__":
    print(f"2020-2026年 Wedge Pop 回测 — AMZN & KLAC")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    symbols = ["AMZN", "KLAC"]
    print(f"\n加载数据中...")
    data = load_data_for_symbols(symbols)
    print(f"成功加载 {len(data)} 只股票数据")

    for symbol in symbols:
        result = backtest_signals(symbol, data)
        print_results(symbol, result)

    # 汇总对比
    print("\n" + "="*80)
    print("汇总对比")
    print("="*80)

    print(f"\n{'股票':<8} {'信号数':>6} {'1日胜率':>8} {'5日胜率':>8} {'10日胜率':>8} {'20日胜率':>8} {'20日收益':>10}")
    print("-" * 60)

    for symbol in symbols:
        result = backtest_signals(symbol, data)
        if "error" not in result and result["signal_count"] > 0:
            s = result["summary"]
            print(f"{symbol:<8} {result['signal_count']:>6} {s[1]['win_rate']:>7.1f}% {s[5]['win_rate']:>7.1f}% {s[10]['win_rate']:>7.1f}% {s[20]['win_rate']:>7.1f}% {s[20]['avg_return']:>9.2f}%")
        else:
            print(f"{symbol:<8} {'N/A':>6}")
