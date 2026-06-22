#!/usr/bin/env python3
"""分析 EMA Crossback / Wedge Pop 买点持仓1天的胜率和收益"""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
import re
import yaml
from data.fetcher import fetch
from universe.manager import get_universe

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

# 获取最新收盘价
symbols = get_universe(cfg)
end_dt = datetime(2026, 5, 13, tzinfo=timezone.utc)
data = fetch(symbols, history_days=10, end_date=end_dt)

prices_latest = {}
for sym, df in data.items():
    if df.empty:
        continue
    prices_latest[sym] = float(df['close'].iloc[-1])

# 解析交易文件
with open('/tmp/trades_full.txt') as f:
    content = f.read()

pattern = re.compile(
    r'\[\s*(\d+)\]\s*(\S+)\s*\n'
    r'\s*买入日期:\s*(\S+)\s*@\s*\$([\d.]+)\s*\n'
    r'\s*卖出日期:\s*(\S+)\s*@\s*\$([\d.]+)\s*\n'
    r'\s*持仓时长:\s*(\d+)\s*天\s*\n'
    r'\s*买入原因:\s*(.+?)\s*\n'
    r'\s*卖出原因:\s*(.+?)\s*\n'
    r'\s*盈亏:\s*([+-]?[\d.]+)%\s*\(\$([+-]?[\d.]+)\)',
    re.MULTILINE
)

trades = []
for m in pattern.finditer(content):
    trade = {
        'num': int(m.group(1)),
        'symbol': m.group(2),
        'entry_date': datetime.strptime(m.group(3), '%Y-%m-%d'),
        'entry_price': float(m.group(4)),
        'exit_date': datetime.strptime(m.group(5), '%Y-%m-%d'),
        'exit_price': float(m.group(6)),
        'holding_days': int(m.group(7)),
        'entry_reason': m.group(8).strip(),
        'exit_reason': m.group(9).strip(),
        'pnl_pct': float(m.group(10)),
        'pnl_dollar': float(m.group(11)),
    }
    trades.append(trade)

# 过滤 Wedge Pop 和 EMA Crossback
wedge_ema = [t for t in trades if 'wedge_pop' in t['entry_reason'].lower() or 'ema_crossback' in t['entry_reason'].lower()]

print(f'=== 分析一：回测中实际持仓1天的 EMA Crossback / Wedge Pop 交易 ===')
hold_1 = [t for t in wedge_ema if t['holding_days'] == 1]
wins_1 = [t for t in hold_1 if t['pnl_pct'] > 0]
losses_1 = [t for t in hold_1 if t['pnl_pct'] <= 0]
print(f'样本数: {len(hold_1)} 个')
if hold_1:
    print(f'胜率: {len(wins_1)/len(hold_1)*100:.1f}% ({len(wins_1)} 涨 / {len(losses_1)} 跌)')
    print(f'平均收益: {sum(t["pnl_pct"] for t in hold_1)/len(hold_1):.2f}%')
    print(f'最大盈利: {max(t["pnl_pct"] for t in hold_1):.2f}%')
    print(f'最大亏损: {min(t["pnl_pct"] for t in hold_1):.2f}%')

print(f'\n=== 分析二：今日收盘价 vs 买入价（估算持仓到今日）===')
results = []
for t in wedge_ema:
    sym = t['symbol']
    if sym in prices_latest and t.get('entry_price'):
        cur_price = prices_latest[sym]
        ret = (cur_price - t['entry_price']) / t['entry_price'] * 100
        results.append({**t, 'cur_price': cur_price, 'sim_ret': ret})

wins = [t for t in results if t['sim_ret'] > 0]
losses = [t for t in results if t['sim_ret'] <= 0]
print(f'样本数: {len(results)} 个')
print(f'胜率: {len(wins)/len(results)*100:.1f}% ({len(wins)} 涨 / {len(losses)} 跌)')
print(f'平均收益: {sum(t["sim_ret"] for t in results)/len(results):.2f}%')
print(f'最大盈利: {max(t["sim_ret"] for t in results):.2f}%')
print(f'最大亏损: {min(t["sim_ret"] for t in results):.2f}%')

# 按持仓时长分组
print(f'\n=== 分析三：按持仓时长分组 ===')
for days in [1, 2, 3, 5, 10]:
    subset = [t for t in wedge_ema if t['holding_days'] == days]
    if subset:
        w = [t for t in subset if t['pnl_pct'] > 0]
        avg = sum(t['pnl_pct'] for t in subset) / len(subset)
        print(f'持仓{days}天: {len(subset)}个, 胜率 {len(w)/len(subset)*100:.1f}%, 均收益 {avg:+.2f}%')
