#!/usr/bin/env python3
"""
Oliver Kell Cycle of Price Action — 2026年完整回测
覆盖所有信号类型：
  买入信号：Wedge Pop, EMA Crossback, Base n' Break, Variant Patterns (VCP/Bull Flag/Bull Pennant)
  做空信号：Wedge Drop Short, Exhaustion Short
持仓管理：固定仓位 $5,000（做空 $5,000，Base n' Break $2,000）
止损：多头 EMA20×0.98，空头 EMA20×1.02
"""

import sys
sys.path.insert(0, '.')
import yaml
import os
from datetime import datetime, timezone
from collections import defaultdict

import pandas as pd
import numpy as np

os.environ['TZ'] = 'UTC'

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

from data.fetcher import fetch
from universe.manager import get_universe
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage
from strategies.v_oliver_kell.oliver_kell_strategy import OKPosition
from strategies.v_oliver_kell.market_environment import MarketEnvironment, MarketState
from strategies.v_oliver_kell.scale_in import ScaleInManager, BatchState
from strategies.v_oliver_kell.exit_manager import ExitManager

# 回测时间段
END_DATE = datetime(2026, 5, 13, tzinfo=timezone.utc)
START_DATE = datetime(2026, 1, 2, tzinfo=timezone.utc)

print(f"回测时间段: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
print()

# 获取股票池
symbols = get_universe(cfg)
print(f"股票数量: {len(symbols)}")

# 获取数据
print("获取数据...")
data = fetch(symbols, history_days=500, end_date=END_DATE)
print(f"成功获取 {len(data)} 只股票数据")
print()

# 提取交易日
all_dates = set()
for sym, df in data.items():
    if df is not None and not df.empty:
        dates = df.index.tolist()
        for d in dates:
            if d.tzinfo is None:
                d = d.tz_localize('UTC')
            if START_DATE <= d <= END_DATE:
                all_dates.add(d)

trading_dates = sorted([d for d in all_dates])
print(f"交易日数量: {len(trading_dates)}")

# 初始化
cycle_detector = CycleDetector()
market_env = MarketEnvironment(cfg)

# 回测结果
trades = []  # 所有交易
daily_portfolio_value = []  # 每日组合价值

# 持仓
positions = {}  # symbol -> {entry_price, shares, entry_date, direction, stop_loss, cycle_stage}

# 回测统计
stats = {
    'wedge_pop': {'count': 0, 'wins': 0, 'total_ret': 0.0, 'losses': 0},
    'ema_crossback': {'count': 0, 'wins': 0, 'total_ret': 0.0, 'losses': 0},
    'base_n_break': {'count': 0, 'wins': 0, 'total_ret': 0.0, 'losses': 0},
    'variant': {'count': 0, 'wins': 0, 'total_ret': 0.0, 'losses': 0},
    'wedge_drop_short': {'count': 0, 'wins': 0, 'total_ret': 0.0, 'losses': 0},
    'exhaustion_short': {'count': 0, 'wins': 0, 'total_ret': 0.0, 'losses': 0},
}

def get_row_for_date(df, date):
    """获取指定日期的行数据"""
    if date.tzinfo is None:
        date = date.tz_localize('UTC')
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize('UTC')
        df = df.copy()
        df.index = idx

    # 找到 <= date 的最后一行
    mask = idx <= date
    if not mask.any():
        return None
    return df.loc[idx[mask][-1]]

def get_prev_day_row(df, date):
    """获取前一天的数据"""
    if date.tzinfo is None:
        date = date.tz_localize('UTC')
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize('UTC')
        df = df.copy()
        df.index = idx

    mask = idx < date
    if not mask.any():
        return None
    return df.loc[idx[mask][-1]]

def slice_to_date(df, date):
    """切片到指定日期"""
    if date.tzinfo is None:
        date = date.tz_localize('UTC')
    idx = df.index
    if idx.tzinfo is None:
        idx = idx.tz_localize('UTC')
        df = df.copy()
        df.index = idx
    return df[idx < date + pd.Timedelta(days=1)]

def classify_and_get_emas(df_to_date):
    """获取分类和 EMA 值"""
    ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
    ema20 = float(df_to_date["close"].ewm(span=20).mean().iloc[-1])
    stage = cycle_detector.classify(df_to_date)
    return stage, ema10, ema20

def is_weekly_uptrend(df):
    """检查周线趋势"""
    if len(df) < 50:
        return True
    ema10 = df["close"].ewm(span=10).mean()
    ema20 = df["close"].ewm(span=20).mean()
    return ema10.iloc[-1] > ema10.iloc[-5] and ema20.iloc[-1] > ema20.iloc[-5]

def is_perfect_stack(df):
    """检查 EMA 多头排列"""
    if len(df) < 50:
        return False
    close = df["close"].iloc[-1]
    ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
    ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])
    ema10_prev = float(df["close"].ewm(span=10).mean().iloc[-2])
    ema20_prev = float(df["close"].ewm(span=20).mean().iloc[-2])
    return close > ema10 > ema20 and ema10 > ema10_prev and ema20 > ema20_prev

def is_bullish_alignment(df):
    """检查看涨排列（宽松版）"""
    if len(df) < 20:
        return False
    close = df["close"].iloc[-1]
    ema10 = float(df["close"].ewm(span=10).mean().iloc[-1])
    ema20 = float(df["close"].ewm(span=20).mean().iloc[-1])
    ema10_prev = float(df["close"].ewm(span=10).mean().iloc[-2])
    ema20_prev = float(df["close"].ewm(span=20).mean().iloc[-2])
    return close > ema10 > ema20 and ema10 > ema10_prev and ema20 > ema20_prev

def get_qqq_data():
    """获取 QQQ 数据"""
    return data.get('QQQ')

def is_rs_leading(df, qqq_df):
    """检查 RS Line 是否领先"""
    if df is None or qqq_df is None or len(df) < 20 or len(qqq_df) < 20:
        return False

    stock_rs = df["close"].iloc[-1] / df["close"].iloc[-20]
    qqq_rs = qqq_df["close"].iloc[-1] / qqq_df["close"].iloc[-20]
    return stock_rs > qqq_rs

# 逐日回测
print("\n开始回测...")
for date_idx, date in enumerate(trading_dates):
    if date < START_DATE:
        continue

    # === Step 1: 市场环境 ===
    qqq_df = get_qqq_data()
    if qqq_df is None or qqq_df.empty:
        continue

    qqq_to_date = slice_to_date(qqq_df, date)
    if len(qqq_to_date) < 25:
        continue

    market_state = market_env.classify(qqq_to_date)

    # === Step 2: 检查持仓止损/出场 ===
    to_close = []
    for sym, pos in list(positions.items()):
        df = data.get(sym)
        if df is None or df.empty:
            to_close.append((sym, 'no_data', None))
            continue

        df_to_date = slice_to_date(df, date)
        if len(df_to_date) < 2:
            to_close.append((sym, 'no_data', None))
            continue

        row = get_row_for_date(df, date)
        if row is None:
            to_close.append((sym, 'no_data', None))
            continue

        current_price = float(row["close"])
        ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
        ema20 = float(df_to_date["close"].ewm(span=20).mean().iloc[-1])
        days_held = (date - pos['entry_date']).days if isinstance(pos['entry_date'], datetime) else 0

        if pos['direction'] == 'long':
            # 多头止损检查
            stop_hit = False
            reason = None

            # 止损：EMA20 × 0.98
            if current_price < ema20 * 0.98:
                stop_hit = True
                reason = 'ema20_break'

            # 止损：固定止损价
            if pos.get('stop_loss') and current_price < pos['stop_loss']:
                stop_hit = True
                reason = 'stop_loss'

            if stop_hit:
                ret_pct = (current_price - pos['entry_price']) / pos['entry_price'] * 100
                trades.append({
                    'symbol': sym,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': pos['entry_price'],
                    'exit_price': current_price,
                    'return_pct': ret_pct,
                    'direction': 'long',
                    'cycle_stage': pos['cycle_stage'],
                    'holding_days': days_held,
                    'exit_reason': reason,
                })
                stats[pos['cycle_stage']]['count'] += 1
                stats[pos['cycle_stage']]['total_ret'] += ret_pct
                if ret_pct > 0:
                    stats[pos['cycle_stage']]['wins'] += 1
                else:
                    stats[pos['cycle_stage']]['losses'] += 1
                to_close.append((sym, reason, current_price))

        elif pos['direction'] == 'short':
            # 空头止损检查
            stop_hit = False
            reason = None

            # 止损：EMA20 × 1.02（做空止损在 EMA20 上方）
            if current_price > ema20 * 1.02:
                stop_hit = True
                reason = 'short_stop'

            if stop_hit:
                ret_pct = (pos['entry_price'] - current_price) / pos['entry_price'] * 100
                trades.append({
                    'symbol': sym,
                    'entry_date': pos['entry_date'],
                    'exit_date': date,
                    'entry_price': pos['entry_price'],
                    'exit_price': current_price,
                    'return_pct': ret_pct,
                    'direction': 'short',
                    'cycle_stage': pos['cycle_stage'],
                    'holding_days': days_held,
                    'exit_reason': reason,
                })
                stats[pos['cycle_stage']]['count'] += 1
                stats[pos['cycle_stage']]['total_ret'] += ret_pct
                if ret_pct > 0:
                    stats[pos['cycle_stage']]['wins'] += 1
                else:
                    stats[pos['cycle_stage']]['losses'] += 1
                to_close.append((sym, reason, current_price))

    # 移除平仓的持仓
    for sym, reason, exit_price in to_close:
        if sym in positions:
            del positions[sym]

    # === Step 3: 扫描买入信号 ===
    if market_state != MarketState.HOSTILE:
        for sym in data.keys():
            if sym in ('SPY', '^VIX', 'QQQ', 'ASHR', 'EWT'):
                continue
            if sym in positions:
                continue

            df = data.get(sym)
            if df is None or df.empty:
                continue

            df_to_date = slice_to_date(df, date)
            if len(df_to_date) < 25:
                continue

            # 周线趋势过滤
            if not is_weekly_uptrend(df_to_date):
                continue

            row = get_row_for_date(df, date)
            if row is None:
                continue
            current_price = float(row["close"])

            # 价格门槛
            if current_price < 10:
                continue

            # EMA 排列过滤
            stage = cycle_detector.classify(df_to_date)
            if stage == CycleStage.EXHAUSTION_EXTENSION:
                continue

            if stage != CycleStage.WEDGE_POP:
                if len(df_to_date) >= 50:
                    if not is_perfect_stack(df_to_date):
                        continue
                elif len(df_to_date) >= 20:
                    if not is_bullish_alignment(df_to_date):
                        continue

            # RS Line 过滤
            if not is_rs_leading(df_to_date, qqq_df):
                continue

            ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
            ema20 = float(df_to_date["close"].ewm(span=20).mean().iloc[-1])

            # Wedge Pop
            if stage == CycleStage.WEDGE_POP:
                wedge_info = cycle_detector.get_wedge_info(df_to_date)
                if wedge_info is not None:
                    today_close = float(df_to_date["close"].iloc[-1])
                    stop = round(today_close * 0.98, 2)
                    positions[sym] = {
                        'entry_price': current_price,
                        'entry_date': date,
                        'direction': 'long',
                        'stop_loss': stop,
                        'cycle_stage': 'wedge_pop',
                        'shares': int(5000 / current_price),
                    }

            # EMA Crossback
            elif stage == CycleStage.EMA_CROSSBACK:
                prev_row = get_prev_day_row(df, date)
                if prev_row is not None:
                    yesterday_low = float(prev_row["low"])
                    stop = round(yesterday_low * 0.99, 2)
                    positions[sym] = {
                        'entry_price': current_price,
                        'entry_date': date,
                        'direction': 'long',
                        'stop_loss': stop,
                        'cycle_stage': 'ema_crossback',
                        'shares': int(5000 / current_price),
                    }

            # Base n' Break
            elif stage == CycleStage.BASE_N_BREAK:
                ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
                stop = round(ema10 * 0.97, 2)
                positions[sym] = {
                    'entry_price': current_price,
                    'entry_date': date,
                    'direction': 'long',
                    'stop_loss': stop,
                    'cycle_stage': 'base_n_break',
                    'shares': int(2000 / current_price),
                }

    # === Step 4: 扫描做空信号 ===
    if len(qqq_to_date) >= 25:
        index_stage = cycle_detector.classify(qqq_to_date)

    if index_stage != CycleStage.WEDGE_DROP:
        for sym in data.keys():
            if sym in ('SPY', '^VIX', 'QQQ', 'ASHR', 'EWT'):
                continue
            if sym in positions:
                continue

            df = data.get(sym)
            if df is None or df.empty:
                continue

            df_to_date = slice_to_date(df, date)
            if len(df_to_date) < 25:
                continue

            row = get_row_for_date(df, date)
            if row is None:
                continue
            current_price = float(row["close"])

            if current_price < 10:
                continue

            stage = cycle_detector.classify(df_to_date)
            ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-1])
            ema20 = float(df_to_date["close"].ewm(span=20).mean().iloc[-1])

            # Wedge Drop Short
            if stage == CycleStage.WEDGE_DROP:
                stop = round(ema20 * 1.02, 2)
                positions[sym] = {
                    'entry_price': current_price,
                    'entry_date': date,
                    'direction': 'short',
                    'stop_loss': stop,
                    'cycle_stage': 'wedge_drop_short',
                    'shares': int(5000 / current_price),
                }

            # Exhaustion Short
            elif stage == CycleStage.EXHAUSTION_EXTENSION:
                prev_row = get_prev_day_row(df, date)
                if prev_row is not None:
                    yesterday_close = float(prev_row["close"])
                    gap_up_pct = (current_price - yesterday_close) / yesterday_close if yesterday_close > 0 else 0
                    if gap_up_pct >= 0.03:
                        today_high = float(row["high"])
                        stop = round(today_high * 1.02, 2)
                        positions[sym] = {
                            'entry_price': current_price,
                            'entry_date': date,
                            'direction': 'short',
                            'stop_loss': stop,
                            'cycle_stage': 'exhaustion_short',
                            'shares': int(5000 / current_price),
                        }

    # 每日输出进度
    if (date_idx + 1) % 20 == 0:
        print(f"  {date.strftime('%Y-%m-%d')} | 持仓: {len(positions)} | 累计交易: {len(trades)}")

print(f"\n回测完成！总交易: {len(trades)} 笔")

# ==================== 统计输出 ====================
print()
print("=" * 80)
print("2026年 Oliver Kell 策略完整回测")
print("=" * 80)

print(f"\n回测区间: {START_DATE.strftime('%Y-%m-%d')} ~ {END_DATE.strftime('%Y-%m-%d')}")
print(f"总交易日: {len(trading_dates)}")
print(f"总交易笔数: {len(trades)}")

# 按信号类型统计
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

print(f"\n{'信号类型':<20} {'交易数':<8} {'胜率':<10} {'平均收益':<12} {'总收益':<12} {'最大收益':<12} {'最大亏损':<12}")
print("-" * 100)

for key, name in signal_names.items():
    s = stats[key]
    if s['count'] == 0:
        print(f"{name:<20} {'0':<8} {'N/A':<10} {'N/A':<12} {'N/A':<12} {'N/A':<12} {'N/A':<12}")
        continue

    win_rate = s['wins'] / s['count'] * 100
    avg_ret = s['total_ret'] / s['count'] if s['count'] > 0 else 0

    # 计算最大收益和最大亏损
    signal_trades = [t for t in trades if t['cycle_stage'] == key]
    if signal_trades:
        rets = [t['return_pct'] for t in signal_trades]
        max_ret = max(rets)
        min_ret = min(rets)
    else:
        max_ret = min_ret = 0

    print(f"{name:<20} {s['count']:<8} {win_rate:>6.1f}%    {avg_ret:>+10.2f}% {s['total_ret']:>+10.2f}% {max_ret:>+10.2f}% {min_ret:>+10.2f}%")

# 汇总统计
all_trades = trades
if all_trades:
    all_rets = [t['return_pct'] for t in all_trades]
    long_trades = [t for t in all_trades if t['direction'] == 'long']
    short_trades = [t for t in all_trades if t['direction'] == 'short']

    print("\n" + "=" * 80)
    print("汇总统计")
    print("=" * 80)

    print(f"\n{'类型':<20} {'交易数':<8} {'胜率':<10} {'平均收益':<12} {'总收益':<12}")
    print("-" * 60)

    if long_trades:
        long_wins = sum(1 for t in long_trades if t['return_pct'] > 0)
        long_rets = [t['return_pct'] for t in long_trades]
        print(f"{'多头交易':<20} {len(long_trades):<8} {long_wins/len(long_trades)*100:>6.1f}%    {np.mean(long_rets):>+10.2f}% {sum(long_rets):>+10.2f}%")

    if short_trades:
        short_wins = sum(1 for t in short_trades if t['return_pct'] > 0)
        short_rets = [t['return_pct'] for t in short_trades]
        print(f"{'空头交易':<20} {len(short_trades):<8} {short_wins/len(short_trades)*100:>6.1f}%    {np.mean(short_rets):>+10.2f}% {sum(short_rets):>+10.2f}%")

    all_wins = sum(1 for t in all_trades if t['return_pct'] > 0)
    print(f"{'全部交易':<20} {len(all_trades):<8} {all_wins/len(all_trades)*100:>6.1f}%    {np.mean(all_rets):>+10.2f}% {sum(all_rets):>+10.2f}%")

    # 按持仓期统计
    print("\n" + "=" * 80)
    print("按持仓天数统计")
    print("=" * 80)

    for days in [1, 5, 10, 20, 60]:
        held_trades = [t for t in all_trades if t['holding_days'] >= days]
        if held_trades:
            rets = [t['return_pct'] for t in held_trades]
            wins = sum(1 for r in rets if r > 0)
            print(f"持仓 ≥{days:>2}天: {len(held_trades):>3}笔, 胜率 {wins/len(held_trades)*100:>5.1f}%, 平均收益 {np.mean(rets):>+6.2f}%")

# 打印前20笔交易明细
print("\n" + "=" * 80)
print("交易明细（前50笔）")
print("=" * 80)
print(f"{'日期':<12} {'股票':<8} {'方向':<6} {'信号类型':<20} {'买入价':<10} {'卖出价':<10} {'收益%':<10} {'持仓天':<8} {'出场原因'}")
print("-" * 110)

for t in sorted(trades, key=lambda x: x['exit_date'])[:50]:
    print(f"{t['exit_date'].strftime('%Y-%m-%d'):<12} {t['symbol']:<8} {t['direction']:<6} {t['cycle_stage']:<20} ${t['entry_price']:<9.2f} ${t['exit_price']:<9.2f} {t['return_pct']:>+8.2f}% {t['holding_days']:<8} {t['exit_reason']}")

print(f"\n... 共 {len(trades)} 笔交易")
