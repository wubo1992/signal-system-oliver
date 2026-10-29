"""
strategies/v_oliver_kell/oneil_rs.py — O'Neil / IBD RS Rating（相对强度评级）

公式（社区复刻口径，非 IBD 官方公式 —— 见下方「口径考据」）：

    RS Raw = 0.4 × ROC(63) + 0.2 × ROC(126) + 0.2 × ROC(189) + 0.2 × ROC(252)
    ROC(N) = close[-1] / close[-1-N] - 1   ← 个股【绝对】涨幅，不除以大盘

    RS Rating = RS Raw 在横截面股票池内的百分位排名，1（最弱）～ 99（最强）。

CAN SLIM 以 RS ≥ 80 作为实际门槛（市场前 20%），SEPA/Trend Template 常用 90+。

最近一个季度占 40% 是刻意设计：O'Neil 观察到新一批牛市的领头羊
在上一轮周期的 12 个月总涨幅往往不是最好的，但 3 个月涨幅一定是最好的，
40% 权重用于更快捕捉新龙头。

## 口径考据（2026-10-22 查证：IBD 从未官方公布过公式）

社区有两种主流复刻，**数学上不等价**。本项目采用 A（用户 2026-10-22 选定）：

```
A. 累计窗口（本项目采用）
   0.4×ROC(63) + 0.2×ROC(126) + 0.2×ROC(189) + 0.2×ROC(252)，四个窗口都从今天起算
   → 与 ibd-rs-rating PyPI、TradingView RS Rating 脚本一致

B. 不重叠季度（CAN SLIM 2002 存档原文）
   "price change this qtr + 1 qtr ago + 2 qtrs ago + 3 qtrs ago"
   → 四个各自独立的季度；部分历史权重用 50/30/20、60/40
```

差异举例：一只平时横盘、6 个月前涨了 100% 的股票
    A 口径 → 0.2×100 + 0.2×104 + 0.2×104 = 41.6   ← 老的强势被重复计入 3 次
    B 口径 → 0.2×100 = 20

实测切到 B 口径的位移：5477 只里仅 404 只不变，中位位移 4，范围 -63 ~ +94
（TXN 86→75、WULF 29→51）。**这是刻意的口径选择，不是 bug，别去「修」。**

另注：**RS Rating 是股票之间互比，ROC 用绝对涨幅、不除以大盘，这是对的**；
跟标普比的是 RS Line（图形指标）。两者经常被混淆。

本项目另有三处有意偏离 IBD：
  1. 部分历史用「剩余权重归一化」（3 季度→50/25/25，2 季度→67/33），
     而非存档的 50/30/20、60/40
  2. 新股进池 —— IBD 对上市不足 3 个月的股票【不给评级】，这是用户明确要求
  3. 剔除权证/优先股/债券/僵尸票，保证横截面是干净的普通股池

另输出「RS 倍数」= 财富指数之比 (1+个股252日涨幅)/(1+基准SPY同期涨幅)，
倍数形式（1.0 = 与大盘同步），与既有 RS (10D)/(20D)/(10W) 三列口径一致。

    ⚠️ 不要改回「个股涨幅 ÷ 基准涨幅」：那个口径在熊市里符号会整个翻转
       （基准跌 10% 时，涨 20% 的股票算出 -2.0）。几何口径恒为正，
       「> 1 = 相对更强」在涨跌市都成立。详见 _relative_strength 的 docstring。

横截面股票池（当前 5474 只）：

  1. 来源 = data/cache/*.pkl 全量，名单见 data/cache/nasdaq_market_caps.json
     （Nasdaq screener 接口生成，美股全市场约 7000 个代码，市值 ≥100 万美元）
  2. 只保留【普通股】：权证 / 单位 / 权 rights / 优先股 / 债券一律剔除
     —— 它们动辄数倍涨幅，会把普通股压到评级分布底部。
     ETF 与 REIT 有意保留，使 RS 评级也能用于 ETF 轮动择时。
     证券类型表见 data/cache/security_types.json
  3. ETF / 指数本身（SPY / QQQ / ^VIX 等）排除，否则基准会给自己打分
  4. 僵尸票排除：最后 K 线落后 SPY 超过 30 天（退市/长期停牌，数据已冻结）

新股（上市未满一年）用【可用窗口权重归一化】参与排名，而不是直接剔除：
    253 根 → 0.4×ROC63 + 0.2×ROC126 + 0.2×ROC189 + 0.2×ROC252（标准口径）
    127 根 → (0.4×ROC63 + 0.2×ROC126) / 0.6
     64 根 → 1.0×ROC63

局限（务必知悉）：
  - 窗口越短口径越「新」，新股评分只反映上市以来的涨幅、不含长期强度，
    热门次新股会排在成熟龙头之前。这是「让新股进池」的必然代价。
  - 实测成熟股（ECPG / AXTI / BVS / EZPW 等）评级不受影响：横截面从 3971
    扩到 5474 只后，它们的评级变动都在 ±2 以内。
  - 新股拿不到 252 日涨幅，所以「RS 倍数」一栏对它们是 None。

注意：RS Rating 是【横截面】指标（个股 vs 全体股票），
      与 RSI（相对强弱指数，时间序列指标）完全不同，两者经常被混淆。
"""

import json
import pickle
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# O'Neil 四季度窗口（交易日）：最近一个季度 40%，其余三个季度各 20%
_QUARTER_LOOKBACKS = (63, 126, 189, 252)
_QUARTER_WEIGHTS = (0.4, 0.2, 0.2, 0.2)

# 计算最短窗口 ROC(63) 至少需要的 K 线根数（要能取到 close[-64]）。
# 完整 252 日窗口需要 253 根；不足的新股按【可用窗口权重归一化】处理，
# 使上市未满一年的股票也能进入横截面排名。
_MIN_BARS = 64
# 252 日累计涨幅（RS 倍数的分子）需要完整窗口
_MIN_BARS_ANNUAL = 253

# 横截面排名时跳过的非个股代码（与 _find_buy_signals 的排除集合保持一致）
_NON_STOCK = frozenset({"SPY", "QQQ", "ASHR", "EWT", "SPX", "^VIX", "VIX"})

# 证券类型表（由 Nasdaq screener 接口生成，见 scripts/build_security_types.py）：
# 排名只保留普通股。ETF / REIT 有意【保留】在池内，以便 RS 评级也能用于 ETF 择时；
# 权证 / 单位 / 权 rights / 优先股 / 债券不是普通股，必须剔除 —— 它们涨幅动辄数倍，
# 会把普通股挤到评级分布的底部。表里没有的代码一律【保留】（未知不作恶）。
_SECURITY_TYPES_FILE = "security_types.json"
_EXCLUDED_KINDS = frozenset({"warrant", "unit", "right", "preferred", "note"})

# 退市/长期停牌过滤：最后 K 线比基准落后超过这个天数就不参与排名。
#
# 为什么用「数据陈旧度」而不是「接口是否收录」来识别僵尸票：
# Nasdaq screener 并不收录全部活跃标的 —— 实测本地有而接口无的 363 个代码里，
# 有 76 个仍在正常交易（BZH / DDT / CECO / ATKR / DDS 等），按接口收录删会误杀。
# 而停更一个多月的数据既不可交易也不该参与相对强度排名，用日期判断是可靠的。
#
# 30 天覆盖了美股长假与正常的停牌缺口；且随着数据自然变陈旧，
# 未来新退市的票会自动掉出，不需要额外维护名单。文件本身一律保留（不删缓存）。
_STALE_DAYS = 30


def _load_non_common(cache_dir: Path | None) -> set[str]:
    """读证券类型表，返回要排除的非普通股代码集合。类型表缺失时返回空集（不排除任何东西）。"""
    if cache_dir is None:
        return set()
    path = cache_dir / _SECURITY_TYPES_FILE
    if not path.exists():
        return set()
    try:
        types = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return {
        symbol.upper()
        for symbol, meta in types.items()
        if isinstance(meta, dict) and meta.get("kind") in _EXCLUDED_KINDS
    }


def _slice_to_date(df: pd.DataFrame, as_of: datetime | None) -> pd.DataFrame:
    """切片到 as_of（含）之后。as_of 为 None 时原样返回。"""
    if as_of is None:
        return df
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    idx = df.index
    if idx.tzinfo is None:
        df = df.copy()
        df.index = idx.tz_localize("UTC")
    return df[df.index <= as_of]


def _get_frame(
    symbol: str,
    market_data: dict[str, pd.DataFrame] | None,
    cache_dir: Path | None,
    as_of: datetime | None,
) -> pd.DataFrame | None:
    """取 symbol 的行情：内存数据优先，其次本地 pkl 缓存。"""
    df = (market_data or {}).get(symbol)
    if df is None and cache_dir is not None:
        cache_file = cache_dir / f"{symbol}.pkl"
        if cache_file.exists():
            try:
                with open(cache_file, "rb") as f:
                    df = pickle.load(f)
            except Exception:
                df = None
    if df is None or df.empty or "close" not in df.columns:
        return None
    return _slice_to_date(df, as_of)


def _close_series(df: pd.DataFrame | None) -> pd.Series | None:
    """取收盘价序列（升序）。K 线不足最短窗口返回 None。"""
    if df is None:
        return None
    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < _MIN_BARS:
        return None
    return close


def _close_array(df: pd.DataFrame | None) -> np.ndarray | None:
    """取收盘价数组（升序）。K 线不足最短窗口返回 None。"""
    close = _close_series(df)
    return None if close is None else close.to_numpy(dtype=float)


def _weighted_annual_return(close: np.ndarray) -> float | None:
    """O'Neil 加权年度涨幅：0.4×ROC(63) + 0.2×ROC(126) + 0.2×ROC(189) + 0.2×ROC(252)。

    上市未满一年的股票取不到全部四个窗口，此时【跳过缺失窗口并把剩余权重归一化】：
        只有 253 根 → 0.4×ROC63 + 0.2×ROC126 + 0.2×ROC189 + 0.2×ROC252
        只有 126 根 → (0.4×ROC63 + 0.2×ROC126) / 0.6
        只有  64 根 → 1.0×ROC63

    注意：窗口越短，口径越「新」，评分只反映近期动能、不含长期强度，
    与完整口径不可直接比较（见 module docstring 的局限说明）。
    """
    last = close[-1]
    if last <= 0:
        return None
    total = 0.0
    weight_sum = 0.0
    for lookback, weight in zip(_QUARTER_LOOKBACKS, _QUARTER_WEIGHTS):
        if len(close) <= lookback:      # 取不到该窗口（要 close[-1-lookback]）
            continue
        base = close[-1 - lookback]
        if base <= 0:
            return None
        total += weight * (last / base - 1.0)
        weight_sum += weight
    if weight_sum == 0:
        return None
    return total / weight_sum          # 权重重新归一化


def _annual_return(close: np.ndarray) -> float | None:
    """252 日累计涨幅。窗口不足返回 None（RS 倍数需要完整 12 个月）。"""
    if len(close) < _MIN_BARS_ANNUAL:
        return None
    last, base = close[-1], close[-1 - 252]
    if last <= 0 or base <= 0:
        return None
    return last / base - 1.0


def _relative_strength(annual: float | None, bench_annual: float | None) -> float | None:
    """
    RS 倍数 = (1 + 个股年涨幅) / (1 + 基准年涨幅) —— 财富指数之比。

    为什么不直接用 `个股涨幅 / 基准涨幅`：那个口径在熊市里符号会整个翻转。
    基准跌 10% 时，一只涨 20% 的股票算出 -2.0（明明在涨却显示负数），
    一只跌 5% 的股票算出 +0.5（明明在跌却显示正数），无法解读。

    改用财富指数后恒为正，且「> 1 = 相对更强」在涨跌市都成立：
      基准 +15.8% / 个股 -7.7%  → 0.80  跑输大盘两成
      基准 -10%  / 个股 -5%    → 1.06  跌得比大盘少一半（熊市里也叫相对强）
    """
    if annual is None or bench_annual is None:
        return None
    denominator = 1.0 + bench_annual
    numerator = 1.0 + annual
    if denominator <= 0 or numerator <= 0:   # 基准或个股归零，数学退化
        return None
    ratio = numerator / denominator
    return float(ratio) if np.isfinite(ratio) else None


def _percentile_ratings(scores: dict[str, float]) -> dict[str, int]:
    """把原始分映射到 1-99 百分位排名（最低 1，最高 99）。"""
    total = len(scores)
    if total == 0:
        return {}
    if total == 1:
        return {symbol: 99 for symbol in scores}
    ratings = {}
    for i, symbol in enumerate(sorted(scores, key=lambda s: scores[s])):
        pct = i / (total - 1)          # 0.0（最弱）～ 1.0（最强）
        ratings[symbol] = int(round(pct * 98)) + 1   # 1 ～ 99
    return ratings


def compute_oneil_rs_map(
    market_data: dict[str, pd.DataFrame],
    as_of: datetime | None = None,
    cache_dir: str | Path | None = None,
    benchmark_symbol: str = "SPY",
) -> dict[str, tuple[int | None, float | None]]:
    """
    计算全股票池的 O'Neil RS Rating（1-99 百分位）与 RS 倍数。

    参数：
        market_data:      symbol -> DataFrame，live mode 已下载的数据，优先于本地缓存
        as_of:            截止日期（含）。None 表示不切片，直接用各自最后一根 K 线
        cache_dir:        本地 pkl 缓存目录。传入后会扫描全量 pkl 扩大横截面
        benchmark_symbol: RS 倍数的基准（SPY）

    返回：
        {symbol: (rating, ratio)}
          rating — 1-99 百分位排名，数据不足为 None
          ratio  — (1+个股252日涨幅)/(1+基准252日涨幅)，财富指数之比，数据不足为 None
    """
    cache_dir = Path(cache_dir) if cache_dir is not None else None

    symbols: set[str] = {s for s in (market_data or {}) if s not in _NON_STOCK}
    if cache_dir is not None and cache_dir.is_dir():
        symbols |= {p.stem for p in cache_dir.glob("*.pkl") if p.stem not in _NON_STOCK}
    symbols.discard(benchmark_symbol)
    # 剔除非普通股（权证/单位/优先股/债券）。ETF 与 REIT 保留。
    symbols -= _load_non_common(cache_dir)

    # 基准 252 日涨幅，作为倍数分母；其最后 K 线日期也是「数据新鲜度」的参照点
    bench_series = _close_series(_get_frame(benchmark_symbol, market_data, cache_dir, as_of))
    bench_return = _annual_return(bench_series.to_numpy() if bench_series is not None else None)
    cutoff = (
        bench_series.index[-1] - pd.Timedelta(days=_STALE_DAYS)
        if bench_series is not None
        else None
    )

    raw_scores: dict[str, float] = {}
    annual_returns: dict[str, float] = {}

    for symbol in sorted(symbols):
        series = _close_series(_get_frame(symbol, market_data, cache_dir, as_of))
        if series is None:
            continue
        if cutoff is not None and series.index[-1] < cutoff:
            continue          # 退市 / 长期停牌：不可交易，不该参与相对强度排名
        close = series.to_numpy(dtype=float)
        score = _weighted_annual_return(close)
        if score is not None:
            raw_scores[symbol] = score
        annual = _annual_return(close)
        if annual is not None:
            annual_returns[symbol] = annual

    ratings = _percentile_ratings(raw_scores)

    result: dict[str, tuple[int | None, float | None]] = {}
    for symbol in set(ratings) | set(annual_returns):
        ratio = _relative_strength(annual_returns.get(symbol), bench_return)
        result[symbol] = (ratings.get(symbol), ratio)

    return result