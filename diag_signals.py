#!/usr/bin/env python3
"""诊断：为什么没有 Wedge Pop"""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
import yaml
from data.fetcher import fetch
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

# 测试几个不同市场的股票
symbols = ['NVDA', 'META', 'TSLA', 'AMD', 'CRM', 'AAPL']
end_dt = datetime(2026, 2, 28, tzinfo=timezone.utc)
data = fetch(symbols, history_days=365, end_date=end_dt)

cd = CycleDetector()

# 检查 2025 年（回测前）是否有 Wedge Pop
print("=== Checking 2025 data for Wedge Pops ===")
for sym in symbols:
    df = data[sym]
    df_2025 = df[(df.index.year == 2025) & (df.index.month >= 11)]
    print(f"\n{sym} - 2025 Nov-Dec bars: {len(df_2025)}")

    for i, (dt, row) in enumerate(df_2025.iterrows()):
        if i < 20:
            continue
        df_to_date = df[df.index <= dt]
        stage = cd.classify(df_to_date)
        if stage == CycleStage.WEDGE_POP:
            print(f"  WP at {dt.date()} | close={row['close']:.2f}")

# 更深入：检查 AAPL 在 2025 年底的价格形态
print("\n=== AAPL late 2025 stage timeline ===")
df = data['AAPL']
df_late = df[df.index >= datetime(2025, 10, 1, tzinfo=timezone.utc)]
for i, (dt, row) in enumerate(df_late.iterrows()):
    if i < 20:
        continue
    df_to_date = df[df.index <= dt]
    stage = cd.classify(df_to_date)
    if stage != CycleStage.UNKNOWN:
        print(f"  {dt.date()} | close={row['close']:.2f} | stage={stage.value}")
