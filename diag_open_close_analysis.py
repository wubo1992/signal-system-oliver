#!/usr/bin/env python3
"""5月12日信号，按5月13日开盘买入，收盘卖出，模拟1天持仓收益"""
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
import yaml
from data.fetcher import fetch
from universe.manager import get_universe
from strategies.v_oliver_kell.oliver_kell_strategy import OliverKellStrategy

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

strategy_cfg = cfg['strategies']['v_oliver_kell']
symbols = get_universe(cfg)
end_dt = datetime(2026, 5, 13, tzinfo=timezone.utc)
data = fetch(symbols, history_days=10, end_date=end_dt)

# 获取 2026-05-12 收盘价（信号日）作为参考
# 2026-05-13 开盘价和收盘价
open_0513 = {}
close_0513 = {}
for sym, df in data.items():
    if df.empty or len(df) < 2:
        continue
    df_sorted = df.sort_index()
    # 找 2026-05-12 和 2026-05-13 的数据
    dates = df_sorted.index.strftime('%Y-%m-%d')
    mask_12 = [d for d in dates if d == '2026-05-12']
    mask_13 = [d for d in dates if d == '2026-05-13']
    if mask_12 and mask_13:
        idx_12 = dates.tolist().index('2026-05-12')
        idx_13 = dates.tolist().index('2026-05-13')
        open_0513[sym] = float(df_sorted['open'].iloc[idx_13])
        close_0513[sym] = float(df_sorted['close'].iloc[idx_13])

print(f'2026-05-13 有数据的股票: {len(open_0513)} 只')

# 用策略扫描 2026-05-12 的信号
strategy = OliverKellStrategy(strategy_config=strategy_cfg, market_data=data, live_mode=True)

class MockQueue:
    def put(self, event): pass

# 扫描 2026-05-12 的信号
sig_date = datetime(2026, 5, 12, tzinfo=timezone.utc)
signals = strategy.run_date(sig_date, MockQueue())
buy_signals = [s for s in signals if s.data.get('direction') == 'buy']

print(f'2026-05-12 买入信号: {len(buy_signals)} 个')

# 计算持仓1天收益（5-13开盘买，收盘卖）
results = []
for s in buy_signals:
    sym = s.symbol
    if sym in open_0513 and sym in close_0513:
        entry = open_0513[sym]   # 5-13 开盘
        exit_px = close_0513[sym]  # 5-13 收盘
        ret = (exit_px - entry) / entry * 100
        results.append({
            'symbol': sym,
            'entry': entry,
            'exit': exit_px,
            'ret': ret,
            'reason': s.data.get('reason', '')
        })

print(f'能匹配到5-13 开收价格的: {len(results)} 个')

wins = [r for r in results if r['ret'] > 0]
losses = [r for r in results if r['ret'] <= 0]

print(f'\n=== 2026-05-12 信号，持仓1天（5-13开盘买，收盘卖）===')
print(f'样本数: {len(results)} 个')
if results:
    print(f'胜率: {len(wins)/len(results)*100:.1f}% ({len(wins)} 涨 / {len(losses)} 跌)')
    print(f'平均收益: {sum(r["ret"] for r in results)/len(results):.2f}%')
    print(f'最大盈利: {max(r["ret"] for r in results):.2f}%')
    print(f'最大亏损: {min(r["ret"] for r in results):.2f}%')

print(f'\n--- 逐笔明细 ---')
for r in sorted(results, key=lambda x: x['ret'], reverse=True):
    print(f"  {r['symbol']:6s} | 开盘: ${r['entry']:.2f} | 收盘: ${r['exit']:.2f} | {r['ret']:+.2f}% | {r['reason'][:50]}")
