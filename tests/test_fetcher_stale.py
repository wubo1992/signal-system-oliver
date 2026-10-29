"""
tests/test_fetcher_stale.py

覆盖 data/fetcher.drop_stale() —— 实盘僵尸票过滤。

背景：Alpaca / Yahoo 都取不到数据时，增量更新会「跳过」，但旧数据仍原样返回。
已退市的票、或 UNIVERSE 里用美股代码代号的欧洲票（THR / COEP / SOI），
会拿着几个月前的收盘价参与策略计算，发出根本不存在的信号。
drop_stale 在 live_mode 下把它们从结果集里剔除（缓存文件一律保留）。
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.fetcher import _STALE_DAYS, _reference_last_date, drop_stale


def make_frame(n, start="2025-06-02"):
    """构造 n 根日线的假 DataFrame。"""
    idx = pd.date_range(start, periods=n, freq="B", tz="UTC")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1000},
        index=idx,
    )


def make_result():
    """三只正常票 + 三只僵尸票，正常票的最后 K 线落在同一天。"""
    fresh_start = "2026-08-01"
    return {
        "SPY": make_frame(60, fresh_start),
        "AAPL": make_frame(60, fresh_start),
        "MSFT": make_frame(60, fresh_start),
        "THR": make_frame(60, "2026-04-24"),     # 落后半年（欧洲票代号）
        "COEP": make_frame(60, "2026-06-24"),    # 落后 3 个月
        "SOI": make_frame(60, "2024-09-11"),     # 落后两年
    }


def last_date(df):
    """最后一根 K 线的日期（去掉时区）。"""
    return df.index[-1].tz_localize(None)


# ── 参照日期 ────────────────────────────────────────────────

def test_reference_prefers_spy():
    """参照点优先用 SPY 的最后 K 线（它代表「市场走到哪天了」）。"""
    result = make_result()
    assert _reference_last_date(result) == last_date(result["SPY"])


def test_reference_falls_back_to_median_without_spy():
    """没有 SPY 时取中位数 —— 用中位数而非最大值，防止个别票日期异常带偏参照点。"""
    result = {k: v for k, v in make_result().items() if k != "SPY"}
    dates = sorted(last_date(df) for df in result.values())
    assert _reference_last_date(result) == dates[len(dates) // 2]


def test_reference_is_none_for_empty_result():
    assert _reference_last_date({}) is None
    assert _reference_last_date({"AAPL": make_frame(0)}) is None


# ── 剔除逻辑 ────────────────────────────────────────────────

def test_stale_tickers_dropped():
    result = drop_stale(make_result())
    assert set(result) == {"SPY", "AAPL", "MSFT"}


def test_fresh_tickers_kept_within_threshold():
    """落后基准 29 天仍在池内，30 天是边界。"""
    last = pd.Timestamp("2026-10-21")
    inside = make_frame(60, (last - pd.Timedelta(days=_STALE_DAYS - 1)).strftime("%Y-%m-%d"))
    assert drop_stale({"SPY": make_frame(60, "2026-08-01"), "ZZZ": inside}) != {}


def test_index_symbols_never_dropped():
    """指数（^VIX 等）数据源更新节奏与个股不同，不参与过滤。"""
    result = {"SPY": make_frame(60, "2026-08-01"), "^VIX": make_frame(60, "2024-01-02")}
    assert "^VIX" in drop_stale(result)


def test_empty_frames_are_preserved():
    """空 DataFrame 原样保留 —— 它的状态由上游的「未获取到数据」处理，不在这里判断。"""
    result = drop_stale({"SPY": make_frame(60, "2026-08-01"), "GONE": pd.DataFrame()})
    assert "GONE" in result


def test_empty_input_returns_empty():
    assert drop_stale({}) == {}


def test_does_not_delete_cache_files():
    """只从返回值剔除，本地 pkl 一律保留 —— 数据没坏，只是这只票不在交易了。"""
    from data.fetcher import CACHE_DIR

    for symbol in ("THR", "COEP", "SOI"):
        assert (CACHE_DIR / f"{symbol}.pkl").exists(), f"{symbol}.pkl 被误删了"