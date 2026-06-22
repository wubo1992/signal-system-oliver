#!/usr/bin/env python3
import sys
sys.path.insert(0, '.')
from datetime import datetime, timezone
import yaml
from data.fetcher import fetch
from universe.manager import get_universe

with open('config.yaml') as f:
    cfg = yaml.safe_load(f)

symbols = get_universe(cfg)
end_dt = datetime(2026, 5, 13, tzinfo=timezone.utc)
data = fetch(symbols, history_days=5, end_date=end_dt)

check_symbols = ['AAPL', 'MSFT', 'GOOG', 'NVDA', 'ARWR', 'GS', 'HAL', 'JD', 'NVDA', 'NWBI', 'OMER', 'SBUX', 'TTMI', 'UNH', 'UNP']
for sym in check_symbols:
    df = data.get(sym)
    if df is not None and len(df) > 0:
        last_date = df.index[-1]
        prev_date = df.index[-2] if len(df) > 1 else None
        with open('/tmp/dates.txt', 'a') as f:
            f.write(f'{sym}: last={last_date}, prev={prev_date}\n')
            f.write(f'  last 3: {[str(d) for d in df.index[-3:]]}\n')
    else:
        with open('/tmp/dates.txt', 'a') as f:
            f.write(f'{sym}: NO DATA\n')
