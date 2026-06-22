"""
Debug script to trace equity curve calculation.
Run with: .venv/bin/python debug_equity.py
"""
import sys
sys.path.insert(0, '/Users/wubo/Desktop/codes/signal_system_Oliver')

from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Monkey-patch the equity curve builder to add debug output
from backtest.engine import BacktestEngine, Trade, _ensure_utc

original_build = BacktestEngine._build_equity_curve

def debug_build_equity_curve(self, closed_trades, market_data, trading_days):
    print(f"\n=== DEBUG EQUITY CURVE ===")
    print(f"Initial capital: ${self.initial_capital:,.2f}")
    print(f"Position size: ${self.position_size}")
    print(f"Trading days: {len(trading_days)}")
    print(f"Closed trades: {len(closed_trades)}")

    if not closed_trades:
        print("NO CLOSED TRADES!")
        return original_build(self, closed_trades, market_data, trading_days)

    # Sort trades by entry date
    sorted_trades = sorted(closed_trades, key=lambda t: _ensure_utc(t.entry_date))
    print(f"\nFirst 5 trades (sorted by entry):")
    for t in sorted_trades[:5]:
        print(f"  {t.symbol}: entry={_ensure_utc(t.entry_date).date()} @ ${t.entry_price:.2f}, "
              f"exit={_ensure_utc(t.exit_date).date() if t.exit_date else 'OPEN'} @ ${t.exit_price or 0:.2f}, "
              f"pnl_pct={t.pnl_pct*100:.2f}%, shares={t.shares:.2f}, pos_dollar=${t.position_dollar:.2f}")

    print(f"\nLast 5 trades:")
    for t in sorted_trades[-5:]:
        print(f"  {t.symbol}: entry={_ensure_utc(t.entry_date).date()} @ ${t.entry_price:.2f}, "
              f"exit={_ensure_utc(t.exit_date).date() if t.exit_date else 'OPEN'} @ ${t.exit_price or 0:.2f}, "
              f"pnl_pct={t.pnl_pct*100:.2f}%, shares={t.shares:.2f}, pos_dollar=${t.position_dollar:.2f}")

    # Calculate what the final equity SHOULD be
    total_pnl = 0.0
    for t in closed_trades:
        if t.position_dollar > 0:
            trade_pnl = t.pnl_pct * t.position_dollar
        else:
            trade_pnl = t.pnl_pct * self.position_size
        total_pnl += trade_pnl

    print(f"\nTotal P&L from {len(closed_trades)} trades: ${total_pnl:,.2f}")
    print(f"Expected final equity: ${self.initial_capital + total_pnl:,.2f}")

    # Run the actual equity calculation
    result = original_build(self, closed_trades, market_data, trading_days)
    equity, max_pos, avg_pos, cap_usage = result

    print(f"\nActual equity curve:")
    print(f"  Start: ${equity.iloc[0]:,.2f}")
    print(f"  End:   ${equity.iloc[-1]:,.2f}")
    print(f"  Change: ${equity.iloc[-1] - equity.iloc[0]:,.2f} ({(equity.iloc[-1]/equity.iloc[0]-1)*100:.2f}%)")
    print(f"  Max: ${equity.max():,.2f}")
    print(f"  Min: ${equity.min():,.2f}")
    print(f"  Max positions: {max_pos}")
    print(f"  Avg positions: {avg_pos:.1f}")

    return result

BacktestEngine._build_equity_curve = debug_build_equity_curve

# Now run the backtest
if __name__ == "__main__":
    from strategies.registry import get_strategy
    from backtest.engine import BacktestEngine

    config = {
        "index_symbol": "QQQ",
        "wedge_lookback": 20,
        "base_lookback": 20,
        "require_wedge_pop_first": True,
    }

    symbols = ["AAPL", "MSFT", "NVDA", "META", "AMZN", "GOOGL"]

    engine = BacktestEngine(
        config=config,
        strategy_cls=get_strategy("v_oliver_kell"),
        strategy_config=config,
        symbols=symbols,
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 5, 7, tzinfo=timezone.utc),
        initial_capital=50000.0,
        position_size=1000.0,
    )

    result = engine.run(verbose=True)

    print("\n\n=== FINAL REPORT ===")
    print(f"Total trades: {result.total_trades}")
    print(f"Win rate: {result.win_rate*100:.1f}%")
    print(f"Profit/Loss ratio: {result.profit_loss_ratio:.2f}")
    print(f"Annualized return: {result.annualized_return*100:.1f}%")
    print(f"Max drawdown: {result.max_drawdown*100:.1f}%")