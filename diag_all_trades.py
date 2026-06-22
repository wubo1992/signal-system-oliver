#!/usr/bin/env python3
"""打印每笔交易详情"""
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
    save_signals_csv=True, strategy_id='v_oliver_kell',
    position_size=5000.0, initial_capital=100000.0,
)
result = engine.run(verbose=False)

trades = sorted([t for t in result.trades if t.exit_date], key=lambda t: t.entry_date)

print(f"总交易笔数: {len(trades)}\n")
for i, t in enumerate(trades, 1):
    pnl_pct = (t.exit_price - t.entry_price) / t.entry_price * 100
    pnl_dollar = (t.exit_price - t.entry_price) * (t.position_dollar / t.entry_price)
    holding = (t.exit_date.date() - t.entry_date.date()).days if t.exit_date and t.entry_date else 0

    print(f"[{i:3d}] {t.symbol}")
    print(f"     买入日期: {t.entry_date.strftime('%Y-%m-%d')}  @ ${t.entry_price:.2f}")
    print(f"     卖出日期: {t.exit_date.strftime('%Y-%m-%d')}  @ ${t.exit_price:.2f}")
    print(f"     持仓时长: {holding} 天")
    print(f"     买入原因: {t.entry_reason}")
    print(f"     卖出原因: {t.exit_reason}")
    print(f"     盈亏: {pnl_pct:+.2f}% (${pnl_dollar:+.0f})")
    print()
