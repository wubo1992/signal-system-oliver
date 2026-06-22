#!/usr/bin/env python3
"""
今日信号股票完整策略回测 — 按持仓期分类
使用完整策略引擎，逐日扫描信号，追踪1/5/10/20天收益
"""
import sys
sys.path.insert(0, '.')
import yaml
import os
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

os.environ['TZ'] = 'UTC'

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

from data.fetcher import fetch
from events import EventQueue
from universe.manager import get_universe
from strategies.v_oliver_kell.oliver_kell_strategy import OliverKellStrategy


TODAY_SIGNALS = ['BVS', 'CAT', 'CRS', 'DAL', 'DELL', 'FCFS', 'FN', 'GEV', 'GNRC', 'GS']

END_DATE = datetime(2026, 5, 13, tzinfo=timezone.utc)
START_DATE = datetime(2026, 1, 2, tzinfo=timezone.utc)


@dataclass
class SignalRecord:
    """记录每个入场信号"""
    symbol: str
    entry_date: datetime
    entry_price: float
    stop: float
    stage: str


def main():
    print("=" * 120)
    print("10只股票 EMA Crossback 完整策略回测 — 按持仓期分类")
    print(f"回测区间: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
    print("=" * 120)

    # 获取数据（包含QQQ和VIX用于市场状态判断）
    print(f"\n获取数据中...")
    all_symbols = TODAY_SIGNALS + ["QQQ", "^VIX"]
    market_data = fetch(all_symbols, history_days=500, end_date=END_DATE)
    print(f"成功获取 {len(market_data)} 只股票数据")

    # 提取交易日
    ref_df = next(iter(market_data.values()))
    ref_index = ref_df.index
    if ref_index.tzinfo is None:
        ref_index = ref_index.tz_localize("UTC")

    trading_days = sorted([
        d for d in ref_index
        if START_DATE <= d <= END_DATE
    ])
    print(f"交易日数量: {len(trading_days)}")

    # 初始化策略
    strategy_config = cfg.get("strategies", {}).get("v_oliver_kell", {})
    strategy = OliverKellStrategy(strategy_config, market_data)

    # 记录所有入场信号
    entry_signals: list[SignalRecord] = []

    # 逐日运行策略
    for day_idx, day in enumerate(trading_days):
        dt = day.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        queue = EventQueue()
        signals = strategy.run_date(dt, queue)

        # 处理信号：只记录买入信号
        for sig in signals:
            if sig.data.get("direction") == "buy":
                entry_signals.append(SignalRecord(
                    symbol=sig.symbol,
                    entry_date=dt,
                    entry_price=sig.data.get("current_price", 0),
                    stop=sig.data.get("stop_loss", 0),
                    stage=sig.data.get("cycle_stage", ""),
                ))

        if (day_idx + 1) % 20 == 0:
            print(f"  {dt.strftime('%Y-%m-%d')} | 累计信号: {len(entry_signals)}")

    print(f"\n共发现 {len(entry_signals)} 个买入信号")

    # 为每个信号计算各持仓期收益
    results = []
    for entry in entry_signals:
        sym = entry.symbol
        df = market_data.get(sym)
        if df is None:
            continue

        # 找到入场日在df中的位置
        entry_idx = None
        for i, idx in enumerate(df.index):
            idx_dt = idx.to_pydatetime()
            if idx_dt.tzinfo is None:
                idx_dt = idx_dt.replace(tzinfo=timezone.utc)
            if idx_dt.date() == entry.entry_date.date():
                entry_idx = i
                break

        if entry_idx is None:
            continue

        entry_price = entry.entry_price
        if entry_price <= 0:
            continue

        # 计算1/5/10/20天收益
        ret_1d = None
        ret_5d = None
        ret_10d = None
        ret_20d = None

        if entry_idx + 1 < len(df):
            ret_1d = (float(df.iloc[entry_idx + 1]["close"]) - entry_price) / entry_price * 100

        if entry_idx + 5 < len(df):
            ret_5d = (float(df.iloc[entry_idx + 5]["close"]) - entry_price) / entry_price * 100

        if entry_idx + 10 < len(df):
            ret_10d = (float(df.iloc[entry_idx + 10]["close"]) - entry_price) / entry_price * 100

        if entry_idx + 20 < len(df):
            ret_20d = (float(df.iloc[entry_idx + 20]["close"]) - entry_price) / entry_price * 100

        results.append({
            'symbol': sym,
            'date': entry.entry_date.strftime('%Y-%m-%d'),
            'entry': entry_price,
            'stop': entry.stop,
            'stage': entry.stage,
            'ret_1d': ret_1d,
            'ret_5d': ret_5d,
            'ret_10d': ret_10d,
            'ret_20d': ret_20d,
        })

    df_results = pd.DataFrame(results)

    # 按股票统计
    print()
    print("=" * 120)
    print("分股票统计")
    print("=" * 120)
    print()
    print(f"{'股票':<8} | {'信号数':<6} | {'1天样本':<6} {'1天胜率':<12} {'1天平均':<10} | {'5天样本':<6} {'5天胜率':<12} {'5天平均':<10} | {'10天样本':<6} {'10天胜率':<12} {'10天平均':<10} | {'20天样本':<6} {'20天胜率':<12} {'20天平均':<10}")
    print("-" * 170)

    for sym in TODAY_SIGNALS:
        s = df_results[df_results['symbol'] == sym]
        n_signals = len(s)
        if n_signals == 0:
            print(f"{sym:<8} | {'—':<6} | 无信号")
            continue

        def stat(key):
            vals = [r[key] for r in s.to_dict('records') if r[key] is not None]
            if not vals:
                return '-', '-', '-'
            n = len(vals)
            wins = sum(1 for v in vals if v > 0)
            avg = np.mean(vals)
            return str(n), f"{wins}/{n}({wins/n*100:.0f}%)", f"{avg:+.2f}%"

        n1, wr1, av1 = stat('ret_1d')
        n5, wr5, av5 = stat('ret_5d')
        n10, wr10, av10 = stat('ret_10d')
        n20, wr20, av20 = stat('ret_20d')

        print(f"{sym:<8} | {n_signals:<6} | {n1:<6} {wr1:<12} {av1:<10} | {n5:<6} {wr5:<12} {av5:<10} | {n10:<6} {wr10:<12} {av10:<10} | {n20:<6} {wr20:<12} {av20:<10}")

    # 总体统计
    print()
    print("=" * 120)
    print("总体统计")
    print("=" * 120)
    print()
    print(f"{'持仓期':<10} | {'样本数':<8} {'胜率':<14} {'平均收益':<12} {'最大收益':<12} {'最小收益':<12}")
    print("-" * 70)

    for key, label in [('ret_1d', '1天'), ('ret_5d', '5天'), ('ret_10d', '10天'), ('ret_20d', '20天')]:
        vals = [r[key] for r in df_results.to_dict('records') if r[key] is not None]
        if not vals:
            continue
        wins = sum(1 for v in vals if v > 0)
        print(f"{label:<10} | {len(vals):<8} {wins}/{len(vals)}({wins/len(vals)*100:.1f}%) {np.mean(vals):>+10.2f}% {np.max(vals):>+10.2f}% {np.min(vals):>+10.2f}%")

    # 逐笔明细
    print()
    print("=" * 120)
    print("逐笔明细")
    print("=" * 120)
    print(f"{'日期':<12} {'股票':<8} {'买入价':<10} {'止损':<10} {'1天':<10} {'5天':<10} {'10天':<10} {'20天':<10}")
    print("-" * 100)
    for r in sorted(df_results.to_dict('records'), key=lambda x: x['date']):
        def fmt(v):
            if v is None:
                return 'N/A'
            return f"{v:+.2f}%"
        print(f"{r['date']:<12} {r['symbol']:<8} ${r['entry']:<9.2f} ${r['stop']:<9.2f} {fmt(r['ret_1d']):<10} {fmt(r['ret_5d']):<10} {fmt(r['ret_10d']):<10} {fmt(r['ret_20d']):<10}")


if __name__ == "__main__":
    main()
