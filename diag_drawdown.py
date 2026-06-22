#!/usr/bin/env python3
"""修复后验证 equity curve"""
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
    position_size=1000.0, initial_capital=50000.0,
)
result = engine.run(verbose=False)

ec = result.equity_curve
peak = ec.cummax()
dd = (ec - peak) / peak

print(f"Max Drawdown: {result.max_drawdown:.1%}")
print(f"Max Positions: {result.max_positions}")
print(f"Annualized Return: {result.annualized_return:.1%}")
print(f"Sharpe: {result.sharpe_ratio:.2f}")

# 检查 1月中附近的 equity
print("\nJan 16-25 equity:")
start_check = datetime(2026, 1, 15, tzinfo=timezone.utc)
end_check = datetime(2026, 1, 25, tzinfo=timezone.utc)
for dt, val in ec.items():
    if start_check <= dt <= end_check:
        p = ec[:dt].max()
        d = (val - p) / p
        print(f"  {dt.date()} | equity={val:.2f} | peak={p:.2f} | dd={d:.2%}")
