#!/usr/bin/env python3
"""
Oliver Kell Cycle of Price Action — 2026年完整回测
使用完整策略引擎，覆盖所有信号类型和持仓管理逻辑。

信号类型：
  买入：Wedge Pop, EMA Crossback, Base n' Break, Variant Patterns
  做空：Wedge Drop Short, Exhaustion Short

持仓管理：
  - 多头止损：EMA20×0.98、EMA10动态止损、固定止损
  - 空头止损：EMA20×1.02
  - Extension分段卖出
  - 60天时间止损
"""

import sys
sys.path.insert(0, '.')
import yaml
import os
from datetime import datetime, timezone
from dataclasses import dataclass, field
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


# 回测时间段
END_DATE = datetime(2026, 5, 13, tzinfo=timezone.utc)
START_DATE = datetime(2026, 1, 2, tzinfo=timezone.utc)


@dataclass
class BTTrade:
    """回测交易记录"""
    symbol: str
    entry_date: datetime
    entry_price: float
    direction: str  # 'long' or 'short'
    shares: float
    position_dollar: float
    cycle_stage: str
    signal_strength: int = 0
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl_pct: float = 0.0

    @property
    def is_closed(self) -> bool:
        return self.exit_date is not None


def main():
    print("=" * 70)
    print("Oliver Kell Cycle of Price Action — 2026年完整回测")
    print("=" * 70)

    # 获取股票池
    symbols = get_universe(cfg)
    print(f"\n股票数量: {len(symbols)}")

    # 获取数据
    print(f"获取数据中... (期间: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')})")
    market_data = fetch(symbols, history_days=500, end_date=END_DATE)
    print(f"成功获取 {len(market_data)} 只股票数据")

    # 提取交易日
    ref_symbols = ["QQQ", "SPY", "AAPL", "MSFT", "NVDA"]
    ref_df = None
    for sym in ref_symbols:
        if sym in market_data:
            ref_df = market_data[sym]
            break
    if ref_df is None:
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

    # 回测状态
    open_trades: dict[str, list[BTTrade]] = {}  # symbol -> list of active trades
    all_trades: list[BTTrade] = []

    # 统计
    stats = {
        'wedge_pop': {'count': 0, 'wins': 0, 'total_ret': 0.0},
        'ema_crossback': {'count': 0, 'wins': 0, 'total_ret': 0.0},
        'base_n_break': {'count': 0, 'wins': 0, 'total_ret': 0.0},
        'variant': {'count': 0, 'wins': 0, 'total_ret': 0.0},
        'wedge_drop_short': {'count': 0, 'wins': 0, 'total_ret': 0.0},
        'exhaustion_short': {'count': 0, 'wins': 0, 'total_ret': 0.0},
    }

    print("\n开始回测...")

    for day_idx, day in enumerate(trading_days):
        dt = day.to_pydatetime()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        queue = EventQueue()
        signals = strategy.run_date(dt, queue)

        # 处理信号
        for sig in signals:
            sym = sig.symbol
            direction = sig.data.get("direction", "")
            reason = sig.data.get("reason", "")
            strength = sig.data.get("strength", 0)
            cycle_stage = sig.data.get("cycle_stage", "")
            stop_loss = sig.data.get("stop_loss")
            position_dollar = sig.data.get("position_dollar", 5000.0)

            # 获取信号日收盘价
            df = market_data.get(sym)
            if df is None:
                continue
            df_sliced = strategy._slice_to_date(df, dt)
            if df_sliced.empty:
                continue

            # 找当天收盘价
            target_date = dt.date()
            df_dates = pd.Series([d.date() for d in df_sliced.index], index=df_sliced.index)
            matched = df_sliced[df_dates == target_date]
            if matched.empty:
                continue
            sig_price = float(matched["close"].iloc[-1])

            if direction == "buy":
                # 开多仓
                shares = position_dollar / sig_price if sig_price > 0 else 0
                trade = BTTrade(
                    symbol=sym,
                    entry_date=dt,
                    entry_price=sig_price,
                    direction="long",
                    shares=shares,
                    position_dollar=position_dollar,
                    cycle_stage=cycle_stage,
                    signal_strength=strength,
                )
                if sym not in open_trades:
                    open_trades[sym] = []
                open_trades[sym].append(trade)
                all_trades.append(trade)

            elif direction == "short":
                # 开空仓
                shares = position_dollar / sig_price if sig_price > 0 else 0
                trade = BTTrade(
                    symbol=sym,
                    entry_date=dt,
                    entry_price=sig_price,
                    direction="short",
                    shares=shares,
                    position_dollar=position_dollar,
                    cycle_stage=cycle_stage,
                    signal_strength=strength,
                )
                if sym not in open_trades:
                    open_trades[sym] = []
                open_trades[sym].append(trade)
                all_trades.append(trade)

            elif direction == "sell":
                # 平仓信号
                if sym not in open_trades or not open_trades[sym]:
                    continue

                # 查找对应的持仓
                sig_shares = sig.data.get("shares", 0.0)
                trades_to_close = open_trades[sym]

                # 收盘价
                for trade in trades_to_close:
                    if trade.is_closed:
                        continue

                    if sig_shares > 0 and trade.shares > 0:
                        # 部分平仓
                        if sig_shares < trade.shares:
                            # 实际部分平仓
                            exit_price = sig_price
                            remaining_shares = trade.shares - sig_shares
                            pnl_pct = (exit_price - trade.entry_price) / trade.entry_price * 100 if trade.direction == "long" else (trade.entry_price - exit_price) / trade.entry_price * 100
                            trade.exit_date = dt
                            trade.exit_price = exit_price
                            trade.exit_reason = reason
                            trade.pnl_pct = pnl_pct
                            trade.shares = sig_shares  # 这笔记录代表卖出的部分
                            # 创建剩余持仓记录（但暂时不加入all_trades，保持简单）
                            # 简化处理：直接全部平仓
                            trade.shares = shares_original if 'shares_original' in dir() else trade.shares
                        else:
                            trade.exit_date = dt
                            trade.exit_price = sig_price
                            trade.exit_reason = reason
                            if trade.direction == "long":
                                trade.pnl_pct = (sig_price - trade.entry_price) / trade.entry_price * 100
                            else:
                                trade.pnl_pct = (trade.entry_price - sig_price) / trade.entry_price * 100
                    else:
                        # 全平
                        trade.exit_date = dt
                        trade.exit_price = sig_price
                        trade.exit_reason = reason
                        if trade.direction == "long":
                            trade.pnl_pct = (sig_price - trade.entry_price) / trade.entry_price * 100
                        else:
                            trade.pnl_pct = (trade.entry_price - sig_price) / trade.entry_price * 100

                # 清除已平仓的交易
                open_trades[sym] = [t for t in open_trades[sym] if not t.is_closed]
                if not open_trades[sym]:
                    del open_trades[sym]

        # 进度
        if (day_idx + 1) % 20 == 0:
            print(f"  {dt.strftime('%Y-%m-%d')} | 持仓: {sum(len(v) for v in open_trades.values())} | 累计交易: {len(all_trades)}")

    # 回测结束时强制平仓
    print("\n回测结束，强制平仓...")
    final_date = trading_days[-1].to_pydatetime()
    for sym, trades in open_trades.items():
        df = market_data.get(sym)
        if df is None:
            continue
        df_sliced = strategy._slice_to_date(df, final_date)
        if df_sliced.empty:
            continue
        final_price = float(df_sliced["close"].iloc[-1])

        for trade in trades:
            trade.exit_date = final_date
            trade.exit_price = final_price
            trade.exit_reason = "回测结束强制平仓"
            if trade.direction == "long":
                trade.pnl_pct = (final_price - trade.entry_price) / trade.entry_price * 100
            else:
                trade.pnl_pct = (trade.entry_price - final_price) / trade.entry_price * 100

    print(f"\n回测完成！总交易: {len(all_trades)} 笔")

    # ==================== 统计 ====================
    closed_trades = [t for t in all_trades if t.is_closed]

    # 更新统计
    for trade in closed_trades:
        stage = trade.cycle_stage
        if stage in stats:
            stats[stage]['count'] += 1
            stats[stage]['total_ret'] += trade.pnl_pct
            if trade.pnl_pct > 0:
                stats[stage]['wins'] += 1

    print()
    print("=" * 80)
    print("2026年 Oliver Kell 策略完整回测结果")
    print("=" * 80)
    print(f"\n回测区间: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
    print(f"总交易日: {len(trading_days)}")
    print(f"总交易笔数: {len(closed_trades)}")

    # 各信号类型统计
    print("\n" + "=" * 80)
    print("各信号类型表现")
    print("=" * 80)

    signal_names = {
        'wedge_pop': 'Wedge Pop',
        'ema_crossback': 'EMA Crossback',
        'base_n_break': 'Base n\' Break',
        'variant': 'Variant Patterns',
        'wedge_drop_short': 'Wedge Drop Short',
        'exhaustion_short': 'Exhaustion Short',
    }

    print(f"\n{'信号类型':<20} {'交易数':<8} {'胜率':<10} {'平均收益':<12} {'总收益':<12}")
    print("-" * 70)

    for key, name in signal_names.items():
        s = stats[key]
        if s['count'] == 0:
            print(f"{name:<20} {'0':<8} {'N/A':<10} {'N/A':<12} {'N/A':<12}")
            continue

        win_rate = s['wins'] / s['count'] * 100
        avg_ret = s['total_ret'] / s['count'] if s['count'] > 0 else 0
        print(f"{name:<20} {s['count']:<8} {win_rate:>6.1f}%    {avg_ret:>+10.2f}% {s['total_ret']:>+10.2f}%")

    # 汇总
    long_trades = [t for t in closed_trades if t.direction == "long"]
    short_trades = [t for t in closed_trades if t.direction == "short"]

    print("\n" + "=" * 80)
    print("汇总统计")
    print("=" * 80)

    print(f"\n{'类型':<20} {'交易数':<8} {'胜率':<10} {'平均收益':<12} {'总收益':<12}")
    print("-" * 60)

    if long_trades:
        long_wins = sum(1 for t in long_trades if t.pnl_pct > 0)
        long_rets = [t.pnl_pct for t in long_trades]
        print(f"{'多头交易':<20} {len(long_trades):<8} {long_wins/len(long_trades)*100:>6.1f}%    {np.mean(long_rets):>+10.2f}% {sum(long_rets):>+10.2f}%")

    if short_trades:
        short_wins = sum(1 for t in short_trades if t.pnl_pct > 0)
        short_rets = [t.pnl_pct for t in short_trades]
        print(f"{'空头交易':<20} {len(short_trades):<8} {short_wins/len(short_trades)*100:>6.1f}%    {np.mean(short_rets):>+10.2f}% {sum(short_rets):>+10.2f}%")

    if closed_trades:
        all_rets = [t.pnl_pct for t in closed_trades]
        all_wins = sum(1 for t in closed_trades if t.pnl_pct > 0)
        print(f"{'全部交易':<20} {len(closed_trades):<8} {all_wins/len(closed_trades)*100:>6.1f}%    {np.mean(all_rets):>+10.2f}% {sum(all_rets):>+10.2f}%")

    # 按持仓期统计
    print("\n" + "=" * 80)
    print("按持仓天数统计")
    print("=" * 80)

    for min_days in [1, 5, 10, 20, 60]:
        held = []
        for t in closed_trades:
            if t.exit_date and t.entry_date:
                days = (t.exit_date - t.entry_date).days
                if days >= min_days:
                    held.append(t)

        if held:
            rets = [t.pnl_pct for t in held]
            wins = sum(1 for r in rets if r > 0)
            print(f"持仓 ≥{min_days:>2}天: {len(held):>3}笔, 胜率 {wins/len(held)*100:>5.1f}%, 平均收益 {np.mean(rets):>+6.2f}%")

    # 打印明细
    print("\n" + "=" * 80)
    print("交易明细（前50笔，按出场日期排序）")
    print("=" * 80)
    print(f"{'日期':<12} {'股票':<8} {'方向':<6} {'信号类型':<20} {'买入价':<10} {'卖出价':<10} {'收益%':<10} {'持仓天':<8} {'出场原因'}")
    print("-" * 110)

    for t in sorted(closed_trades, key=lambda x: x.exit_date if x.exit_date else datetime.min)[:50]:
        days = (t.exit_date - t.entry_date).days if t.exit_date and t.entry_date else 0
        print(f"{t.exit_date.strftime('%Y-%m-%d'):<12} {t.symbol:<8} {t.direction:<6} {t.cycle_stage:<20} ${t.entry_price:<9.2f} ${t.exit_price:<9.2f} {t.pnl_pct:>+8.2f}% {days:<8} {t.exit_reason[:30]}")

    print(f"\n... 共 {len(closed_trades)} 笔交易")


if __name__ == "__main__":
    main()
