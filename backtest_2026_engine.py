#!/usr/bin/env python3
"""
Oliver Kell Cycle of Price Action — 2026年完整回测
使用 BacktestEngine 完整策略引擎
"""

import sys
import os
sys.path.insert(0, '.')
import yaml
from datetime import datetime, timezone

os.environ['TZ'] = 'UTC'

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

from backtest.engine import BacktestEngine
from universe.manager import get_universe
from strategies.v_oliver_kell.oliver_kell_strategy import OliverKellStrategy

# 回测时间段
END_DATE = datetime(2026, 5, 13, tzinfo=timezone.utc)
START_DATE = datetime(2026, 1, 2, tzinfo=timezone.utc)

# 获取股票池
symbols = get_universe(cfg)
print(f"股票池: {len(symbols)} 只")
print(f"回测区间: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")

# 策略配置
strategy_config = cfg.get("strategies", {}).get("v_oliver_kell", {})

# 运行回测
engine = BacktestEngine(
    config=cfg,
    strategy_cls=OliverKellStrategy,
    strategy_config=strategy_config,
    symbols=symbols,
    start_date=START_DATE,
    end_date=END_DATE,
    position_size=5000.0,  # 每笔5000美元
    initial_capital=50000.0,  # 初始本金5万
)

print("\n开始回测...")
result = engine.run(verbose=True)
result.print_report(strategy_name="Oliver Kell Cycle of Price Action")
