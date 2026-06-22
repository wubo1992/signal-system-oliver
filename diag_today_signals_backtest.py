#!/usr/bin/env python3
"""
今日买入信号股票，过去1年 EMA Crossback 回测
买入：EMA Crossback 确认日收盘价
止损：回踩日最低价 × 0.99
持仓：1天、5天、20天、60天
"""
import sys
sys.path.insert(0, '.')
import yaml
import os
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np
os.environ['TZ'] = 'UTC'

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

from data.fetcher import fetch
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage

# 今日信号股票
TODAY_SIGNALS = ['AMZN', 'BA', 'BE', 'BVS', 'CORZ', 'CRS', 'CSTM', 'DAL', 'DELL', 'GOOG']

# 回测时间段
END_DATE = datetime(2026, 5, 13, tzinfo=timezone.utc)
START_DATE = datetime(2025, 5, 14, tzinfo=timezone.utc)

print(f"回测时间段: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
print(f"股票: {TODAY_SIGNALS}")
print()

# 获取数据
data = fetch(TODAY_SIGNALS, history_days=500, end_date=END_DATE)

cycle_detector = CycleDetector()

results = []

for sym in TODAY_SIGNALS:
    df = data.get(sym)
    if df is None or df.empty:
        print(f"{sym}: 无数据")
        continue

    df_sorted = df.sort_index()
    df_sorted = df_sorted[df_sorted.index >= START_DATE]

    if len(df_sorted) < 30:
        print(f"{sym}: 数据不足")
        continue

    # 逐日扫描 EMA Crossback 信号
    for i in range(25, len(df_sorted) - 5):
        row = df_sorted.iloc[i]
        prev_row = df_sorted.iloc[i - 1]

        date = row.name
        if date.tzinfo is None:
            date = date.tz_localize("UTC")

        if date > END_DATE:
            break

        df_to_date = df_sorted.iloc[:i + 1]
        close = float(row["close"])
        close_prev = float(prev_row["close"])

        # 计算 EMA
        ema10_series = df_to_date["close"].ewm(span=10).mean()
        ema20_series = df_to_date["close"].ewm(span=20).mean()
        ema10 = float(ema10_series.iloc[-1])
        ema10_prev = float(ema10_series.iloc[-2])
        ema20 = float(ema20_series.iloc[-1])

        # 获取昨天（回踩日）
        y_close = float(prev_row["close"])
        y_low = float(prev_row["low"])
        y_high = float(prev_row["high"])
        y_vol = float(prev_row["volume"])

        # === EMA Crossback 条件 ===
        # 1. EMA10 > 前日EMA10（上升）
        if not (ema10 > ema10_prev):
            continue

        # 2. Day 1：价格在 EMA10 附近（±5%）
        if y_close > ema10 * 1.05 or y_close < ema10 * 0.95:
            continue

        # 3. Day 1：低点测试 EMA
        if y_low > ema10 * 1.05 or y_low < ema10 * 0.95:
            continue

        # 4. Day 2（今天）：收盘 > Day 1 收盘
        if close <= y_close:
            continue

        # 5. Day 2：收盘在当日波幅上半部
        day_range = float(row["high"]) - float(row["low"])
        if day_range > 0 and close < float(row["low"]) + day_range * 0.5:
            continue

        # 6. Day 2：收盘 > EMA10
        if close <= ema10:
            continue

        # === 信号确认！计算各持仓期收益 ===
        entry_price = close
        stop_price = round(y_low * 0.99, 2)

        # 持仓1天
        if i + 1 < len(df_sorted):
            exit_1d = float(df_sorted.iloc[i + 1]["close"])
            ret_1d = (exit_1d - entry_price) / entry_price * 100
        else:
            ret_1d = None

        # 持仓5天
        if i + 5 < len(df_sorted):
            exit_5d = float(df_sorted.iloc[i + 5]["close"])
            ret_5d = (exit_5d - entry_price) / entry_price * 100
        else:
            ret_5d = None

        # 持仓20天
        if i + 20 < len(df_sorted):
            exit_20d = float(df_sorted.iloc[i + 20]["close"])
            ret_20d = (exit_20d - entry_price) / entry_price * 100
        else:
            ret_20d = None

        # 持仓60天
        if i + 60 < len(df_sorted):
            exit_60d = float(df_sorted.iloc[i + 60]["close"])
            ret_60d = (exit_60d - entry_price) / entry_price * 100
        else:
            ret_60d = None

        results.append({
            'symbol': sym,
            'date': date.strftime('%Y-%m-%d'),
            'entry': entry_price,
            'stop': stop_price,
            'ret_1d': ret_1d,
            'ret_5d': ret_5d,
            'ret_20d': ret_20d,
            'ret_60d': ret_60d,
        })

# ==================== 统计 ====================
print(f"=" * 80)
print(f"共发现 {len(results)} 个 EMA Crossback 信号")
print(f"=" * 80)

if not results:
    print("无信号")
    sys.exit(0)

# 按股票统计
print(f"\n{'股票':<8} {'信号数':<6} {'1天胜率':<10} {'5天胜率':<10} {'20天胜率':<10} {'60天胜率':<10}")
print("-" * 70)

for sym in TODAY_SIGNALS:
    sym_results = [r for r in results if r['symbol'] == sym]
    if not sym_results:
        continue

    n = len(sym_results)

    def win_rate(ret_key):
        vals = [r[ret_key] for r in sym_results if r[ret_key] is not None]
        if not vals:
            return "N/A"
        wins = sum(1 for v in vals if v > 0)
        return f"{wins}/{len(vals)} ({wins/len(vals)*100:.0f}%)"

    def avg_ret(ret_key):
        vals = [r[ret_key] for r in sym_results if r[ret_key] is not None]
        if not vals:
            return "N/A"
        return f"{np.mean(vals):.2f}%"

    print(f"{sym:<8} {n:<6} {win_rate('ret_1d'):<10} {win_rate('ret_5d'):<10} {win_rate('ret_20d'):<10} {win_rate('ret_60d'):<10}")

# 总体统计
all_1d = [r['ret_1d'] for r in results if r['ret_1d'] is not None]
all_5d = [r['ret_5d'] for r in results if r['ret_5d'] is not None]
all_20d = [r['ret_20d'] for r in results if r['ret_20d'] is not None]
all_60d = [r['ret_60d'] for r in results if r['ret_60d'] is not None]

def overall_stats(vals, label):
    if not vals:
        print(f"{label}: N/A")
        return
    wins = sum(1 for v in vals if v > 0)
    print(f"{label}: 样本{n}, 胜率{wins}/{len(vals)}({wins/len(vals)*100:.1f}%), 平均收益{np.mean(vals):.2f}%, 最大{np.max(vals):.2f}%, 最小{np.min(vals):.2f}%")

print()
print("=" * 80)
print("总体统计")
print("=" * 80)
overall_stats(all_1d, "持仓1天")
overall_stats(all_5d, "持仓5天")
overall_stats(all_20d, "持仓20天")
overall_stats(all_60d, "持仓60天")

# 打印明细
print()
print("=" * 80)
print("逐笔明细")
print("=" * 80)
print(f"{'日期':<12} {'股票':<8} {'买入价':<10} {'止损':<10} {'1天':<10} {'5天':<10} {'20天':<10} {'60天':<10}")
print("-" * 90)
for r in sorted(results, key=lambda x: x['date']):
    def fmt(v):
        if v is None:
            return "N/A"
        return f"{v:+.2f}%"
    print(f"{r['date']:<12} {r['symbol']:<8} ${r['entry']:<9.2f} ${r['stop']:<9.2f} {fmt(r['ret_1d']):<10} {fmt(r['ret_5d']):<10} {fmt(r['ret_20d']):<10} {fmt(r['ret_60d']):<10}")
