#!/usr/bin/env python3
"""分析策略容量和持仓能力"""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
import yaml
from data.fetcher import fetch
from strategies.v_oliver_kell.oliver_kell_strategy import OliverKellStrategy
from backtest.engine import BacktestEngine
from universe.manager import get_universe

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

strategy_cfg = cfg['strategies']['v_oliver_kell']
symbols = get_universe(cfg)
end_dt = datetime(2026, 5, 7, tzinfo=timezone.utc)
data = fetch(symbols, history_days=365, end_date=end_dt)

class DiagStrategy(OliverKellStrategy):
    pass

engine = BacktestEngine(
    config=cfg, strategy_cls=DiagStrategy, strategy_config=strategy_cfg,
    symbols=symbols,
    start_date=datetime(2026, 1, 2, tzinfo=timezone.utc),
    end_date=datetime(2026, 5, 7, tzinfo=timezone.utc),
    save_signals_csv=False, strategy_id='v_oliver_kell',
    position_size=5000.0, initial_capital=100000.0,
)
result = engine.run(verbose=False)

# 分析持仓分布
trades = result.trades
print(f"=== 容量分析 ===")
print(f"初始本金: $50,000")
print(f"每笔交易金额: $1,000")
print(f"理论最大持仓: {50000/1000:.0f} 股")
print(f"实际峰值持仓: {result.max_positions} 股")
print(f"平均持仓: {result.avg_positions:.1f} 股")
print(f"总交易笔数: {len(trades)}")

# 分析交易频率
entry_dates = sorted(set(t.entry_date.date() for t in trades if t.entry_date))
print(f"\n交易天数: {len(entry_dates)} 天")
print(f"总交易日: ~86 天 (2026-01-02 ~ 2026-05-07)")
print(f"日均交易: {len(trades)/86:.1f} 笔/天")
print(f"月均交易: {len(trades)/4.14:.1f} 笔/月")

# 分析持仓周期
holding_days = []
for t in trades:
    if t.exit_date and t.entry_date:
        hd = (t.exit_date.date() - t.entry_date.date()).days
        holding_days.append(hd)

if holding_days:
    import numpy as np
    holding_days.sort()
    print(f"\n持仓时长:")
    print(f"  最短: {min(holding_days)} 天")
    print(f"  最长: {max(holding_days)} 天")
    print(f"  中位数: {holding_days[len(holding_days)//2]} 天")
    print(f"  平均: {np.mean(holding_days):.1f} 天")

# 分析每日新信号数分布
from collections import Counter
daily_signals = Counter()
for t in trades:
    daily_signals[t.entry_date.date()] += 1

signal_counts = sorted(daily_signals.values())
if signal_counts:
    print(f"\n每日新信号数分布:")
    print(f"  最多: {max(signal_counts)} 笔/天")
    print(f"  最少: {min(signal_counts)} 笔/天")
    print(f"  平均: {np.mean(signal_counts):.1f} 笔/天")
    print(f"  中位数: {signal_counts[len(signal_counts)//2]} 笔/天")

# 容量问题分析
max_capital_per_trade = 1000
max_positions = 50  # $50,000 / $1,000
print(f"\n=== 容量限制 ===")
print(f"最大可容纳持仓: {max_positions} 股 (每笔 $1,000)")
print(f"实际峰值: {result.max_positions} 股")
print(f"容量利用率: {result.max_positions/max_positions*100:.1f}%")

# 如果把 position_size 提高到 $5,000
print(f"\n如果每笔交易 $5,000:")
print(f"  最大持仓: {50000/5000:.0f} 股")
print(f"  每月理论最大交易额: $5,000 × {151.5:.0f} = ${5*151.5*1000/1000:.0f}K")
print(f"  年交易额: ${5*151.5*12*1000/1000:.0f}K")
