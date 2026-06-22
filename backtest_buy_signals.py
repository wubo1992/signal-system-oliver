"""
买入信号回测脚本
对今日（2026-05-22）出现的每只买入信号股票，回测其2026年内同类信号的表现。
"""

import sys
sys.path.insert(0, '.')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from tqdm import tqdm
import warnings
warnings.filterwarnings('ignore')

from strategies.v_oliver_kell.cycle_detector import CycleDetector
from data.fetcher import fetch


# 今日买入信号
TODAY_SIGNALS = {
    # Wedge Pop
    "GFS": "wedge_pop",

    # EMA Crossback
    "ADI": "ema_crossback",
    "AMD": "ema_crossback",
    "ARW": "ema_crossback",
    "ASX": "ema_crossback",
    "CAMT": "ema_crossback",
    "CAR": "ema_crossback",
    "CRWD": "ema_crossback",
    "DHI": "ema_crossback",
    "DXPE": "ema_crossback",
    "ELA": "ema_crossback",
    "ELMD": "ema_crossback",
    "ESTA": "ema_crossback",
    "ETN": "ema_crossback",
    "FCFS": "ema_crossback",
    "FSBC": "ema_crossback",
    "FTV": "ema_crossback",
    "HUT": "ema_crossback",
    "IREN": "ema_crossback",
    "ITRN": "ema_crossback",
    "KEYS": "ema_crossback",
    "KINS": "ema_crossback",
    "KN": "ema_crossback",
    "LSCC": "ema_crossback",
    "MTSI": "ema_crossback",
    "MXL": "ema_crossback",
    "MYFW": "ema_crossback",
    "NWBI": "ema_crossback",
    "OKTA": "ema_crossback",
    "OPLN": "ema_crossback",
    "PANW": "ema_crossback",
    "PSMT": "ema_crossback",
    "SIF": "ema_crossback",
    "TSEM": "ema_crossback",
    "TSM": "ema_crossback",
    "TXN": "ema_crossback",
    "UMC": "ema_crossback",
    "XIFR": "ema_crossback",

    # Base n' Break
    "CAT": "base_n_break",
}

START_DATE = "2026-01-01"
END_DATE = "2026-06-17"


def find_signal_dates(df: pd.DataFrame, signal_type: str) -> list:
    """找2026年内所有指定类型的信号日期"""
    signals = []
    detector = CycleDetector()

    if len(df) < 25:
        return signals

    for i in range(25, len(df)):
        row_date = df.index[i]
        df_slice = df.iloc[:i+1]
        stage = detector.classify(df_slice)
        if stage.value == signal_type:
            signals.append(row_date)

    return signals


def backtest_signal(df: pd.DataFrame, signal_date, hold_days: int) -> dict:
    """计算某次信号买入后持有N天的收益"""
    signal_price = float(df.loc[signal_date, "close"])

    future_dates = df.index[df.index > signal_date]
    if len(future_dates) < hold_days:
        return None

    future_date = future_dates[hold_days - 1]
    future_close = float(df.loc[future_date, "close"])

    gain_pct = (future_close - signal_price) / signal_price * 100
    win = gain_pct > 0

    return {
        "gain_pct": gain_pct,
        "win": win,
        "future_close": future_close,
        "signal_price": signal_price,
        "future_date": future_date,
    }


def backtest_stock(symbol: str, signal_type: str) -> dict:
    """对某只股票的回测"""
    data = fetch([symbol], history_days=300, live_mode=False)
    if not data or symbol not in data:
        return None

    df = data[symbol]
    df = df[(df.index >= START_DATE) & (df.index <= END_DATE)]

    signals = find_signal_dates(df, signal_type)
    if not signals:
        return {"symbol": symbol, "signal_type": signal_type, "signals": [], "results": {}}

    results = {}
    for hold in [1, 5, 10, 20]:
        entries = []
        for sig_date in signals:
            result = backtest_signal(df, sig_date, hold)
            if result is not None:
                entries.append(result)

        if entries:
            gains = [e["gain_pct"] for e in entries]
            wins = sum(1 for e in entries if e["win"])
            win_rate = wins / len(entries) * 100
            avg_gain = np.mean(gains)
            results[f"{hold}d"] = {
                "win_rate": win_rate,
                "avg_gain": avg_gain,
                "count": len(entries),
                "wins": wins,
            }
        else:
            results[f"{hold}d"] = {"win_rate": 0, "avg_gain": 0, "count": 0, "wins": 0}

    return {
        "symbol": symbol,
        "signal_type": signal_type,
        "signals": signals,
        "results": results,
    }


def main():
    print("=" * 80)
    print("Oliver Kell 买入信号回测 — 2026年（今日信号: 2026-06-19）")
    print(f"回测区间: {START_DATE} ~ {END_DATE}")
    print(f"今日信号股票数: {len(TODAY_SIGNALS)}")
    print("=" * 80)

    all_results = []

    for symbol, signal_type in tqdm(TODAY_SIGNALS.items(), desc="回测中"):
        result = backtest_stock(symbol, signal_type)
        if result:
            all_results.append(result)

    wedge_pop_stocks = [r for r in all_results if r["signal_type"] == "wedge_pop"]
    ema_crossback_stocks = [r for r in all_results if r["signal_type"] == "ema_crossback"]
    base_n_break_stocks = [r for r in all_results if r["signal_type"] == "base_n_break"]

    header = f"{'股票':<8} {'信号数':>6} {'1d胜率':>8} {'1d收益':>8} {'5d胜率':>8} {'5d收益':>8} {'10d胜率':>8} {'10d收益':>10} {'20d胜率':>8} {'20d收益':>10}"
    sep = "-" * 100

    # Wedge Pop
    print("\n" + "=" * 100)
    print("【Wedge Pop】信号回测")
    print("=" * 100)
    print(header)
    print(sep)
    for r in wedge_pop_stocks:
        res = r["results"]
        n = len(r["signals"])
        r1 = res.get('1d', {})
        r5 = res.get('5d', {})
        r10 = res.get('10d', {})
        r20 = res.get('20d', {})
        print(f"{r['symbol']:<8} {n:>6} "
              f"{r1.get('win_rate', 0):>7.1f}% {r1.get('avg_gain', 0):>7.2f}% "
              f"{r5.get('win_rate', 0):>7.1f}% {r5.get('avg_gain', 0):>7.2f}% "
              f"{r10.get('win_rate', 0):>7.1f}% {r10.get('avg_gain', 0):>9.2f}% "
              f"{r20.get('win_rate', 0):>7.1f}% {r20.get('avg_gain', 0):>9.2f}%")

    # EMA Crossback
    print("\n" + "=" * 100)
    print("【EMA Crossback】信号回测")
    print("=" * 100)
    print(header)
    print(sep)
    for r in sorted(ema_crossback_stocks, key=lambda x: -len(x["signals"])):
        res = r["results"]
        n = len(r["signals"])
        r1 = res.get('1d', {})
        r5 = res.get('5d', {})
        r10 = res.get('10d', {})
        r20 = res.get('20d', {})
        print(f"{r['symbol']:<8} {n:>6} "
              f"{r1.get('win_rate', 0):>7.1f}% {r1.get('avg_gain', 0):>7.2f}% "
              f"{r5.get('win_rate', 0):>7.1f}% {r5.get('avg_gain', 0):>7.2f}% "
              f"{r10.get('win_rate', 0):>7.1f}% {r10.get('avg_gain', 0):>9.2f}% "
              f"{r20.get('win_rate', 0):>7.1f}% {r20.get('avg_gain', 0):>9.2f}%")

    # Base n' Break
    print("\n" + "=" * 100)
    print("【Base n' Break】信号回测")
    print("=" * 100)
    print(header)
    print(sep)
    for r in base_n_break_stocks:
        res = r["results"]
        n = len(r["signals"])
        r1 = res.get('1d', {})
        r5 = res.get('5d', {})
        r10 = res.get('10d', {})
        r20 = res.get('20d', {})
        print(f"{r['symbol']:<8} {n:>6} "
              f"{r1.get('win_rate', 0):>7.1f}% {r1.get('avg_gain', 0):>7.2f}% "
              f"{r5.get('win_rate', 0):>7.1f}% {r5.get('avg_gain', 0):>7.2f}% "
              f"{r10.get('win_rate', 0):>7.1f}% {r10.get('avg_gain', 0):>9.2f}% "
              f"{r20.get('win_rate', 0):>7.1f}% {r20.get('avg_gain', 0):>9.2f}%")


if __name__ == "__main__":
    main()
