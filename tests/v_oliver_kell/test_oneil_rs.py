"""
tests/v_oliver_kell/test_oneil_rs.py

覆盖 O'Neil RS 的两块逻辑：
  1. 新股「可用窗口权重归一化」（_weighted_annual_return / _annual_return）
  2. 非普通股剔除（_load_non_common，权证/优先股/债券排除，ETF 保留）
"""

import json

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from strategies.v_oliver_kell.oneil_rs import (
    _EXCLUDED_KINDS,
    _STALE_DAYS,
    _annual_return,
    _close_array,
    _load_non_common,
    _relative_strength,
    _weighted_annual_return,
    compute_oneil_rs_map,
)


def make_close(prices):
    """构造只有一个 close 列的 DataFrame。"""
    idx = pd.date_range("2024-01-01", periods=len(prices), tz="UTC")
    return pd.DataFrame({"close": prices}, index=idx)


def make_series(n, growth_per_bar):
    """构造长度 n、每根等比增长 growth 的价格序列。

    于是 close[-1]/close[-1-N] - 1 = (1+g)^N - 1，ROC(N) 完全可预期。
    """
    base = np.array([100.0 * (1 + growth_per_bar) ** i for i in range(n)])
    return base


# ── 窗口权重 ────────────────────────────────────────────────

def test_full_history_uses_four_windows():
    """K 线够长时用标准四窗口权重 0.4/0.2/0.2/0.2。"""
    g = 0.001
    close = make_series(300, g)
    score = _weighted_annual_return(close)

    expected = (
        0.4 * ((1 + g) ** 63 - 1)
        + 0.2 * ((1 + g) ** 126 - 1)
        + 0.2 * ((1 + g) ** 189 - 1)
        + 0.2 * ((1 + g) ** 252 - 1)
    )
    assert score == pytest.approx(expected)


def test_short_history_renormalizes_available_weights():
    """只有 127 根时，ROC(63)+ROC(126) 可用，189/252 被跳过，权重归一化到 0.6。"""
    g = 0.001
    close = make_series(127, g)
    score = _weighted_annual_return(close)

    expected = (0.4 * ((1 + g) ** 63 - 1) + 0.2 * ((1 + g) ** 126 - 1)) / 0.6
    assert score == pytest.approx(expected)


def test_window_needs_one_extra_bar():
    """ROC(N) 要取 close[-1-N]，所以长度必须 >= N+1：126 根取不到 ROC(126)。"""
    g = 0.001
    assert _weighted_annual_return(make_series(126, g)) == pytest.approx(
        (1 + g) ** 63 - 1
    )
    assert _weighted_annual_return(make_series(127, g)) == pytest.approx(
        (0.4 * ((1 + g) ** 63 - 1) + 0.2 * ((1 + g) ** 126 - 1)) / 0.6
    )


def test_minimum_history_collapses_to_single_window():
    """只有 64 根时只剩 ROC(63) 一个窗口，归一化后权重为 1.0。"""
    g = 0.001
    close = make_series(64, g)
    score = _weighted_annual_return(close)

    assert score == pytest.approx((1 + g) ** 63 - 1)


def test_score_is_larger_for_faster_growth():
    """同一历史长度下，涨幅越大评分越高（百分位排名的前提）。"""
    assert _weighted_annual_return(make_series(300, 0.002)) > _weighted_annual_return(
        make_series(300, 0.001)
    )


# ── 数据长度门槛 ────────────────────────────────────────────

def test_close_array_rejects_history_shorter_than_shortest_window():
    """不足 ROC(63) 所需的 64 根 → None。"""
    assert _close_array(make_close([100.0] * 63)) is None
    assert _close_array(make_close([100.0] * 64)) is not None


def test_annual_return_none_for_new_listings():
    """新股算不出 252 日涨幅 → RS 倍数应为 None。"""
    assert _annual_return(make_series(126, 0.001)) is None
    assert _annual_return(make_series(252, 0.001)) is None  # 需 close[-253]
    assert _annual_return(make_series(300, 0.001)) == pytest.approx((1.001) ** 252 - 1)


# ── 非普通股剔除 ────────────────────────────────────────────

@pytest.fixture
def type_cache(tmp_path):
    """伪造一个证券类型表缓存目录。"""
    types = {
        "GOOD": {"name": "Good Corp. Common Stock", "kind": "common"},
        "WARR": {"name": "Good Corp. Warrant", "kind": "warrant"},
        "PREF": {"name": "Good Corp. Preferred Stock", "kind": "preferred"},
        "NOTE": {"name": "Good Corp. Senior Notes Due 2030", "kind": "note"},
        "UNIT": {"name": "Good Corp. Units", "kind": "unit"},
        "ADR": {"name": "Good Corp. American Depositary Shares", "kind": "common"},
    }
    (tmp_path / "security_types.json").write_text(json.dumps(types), encoding="utf-8")
    return tmp_path


def test_non_common_securities_excluded(type_cache):
    excluded = _load_non_common(type_cache)
    assert excluded == {"WARR", "PREF", "NOTE", "UNIT"}
    assert "GOOD" not in excluded
    assert "ADR" not in excluded          # ADR 代表普通股权益，必须保留


def test_etf_is_not_excluded(type_cache):
    """ETF 有意保留在池内（RS 评级也要能用于 ETF 轮动）。"""
    (type_cache / "security_types.json").write_text(
        json.dumps({"FUND": {"name": "Some Sector SPDR ETF Trust", "kind": "common"}}),
        encoding="utf-8",
    )
    assert _load_non_common(type_cache) == set()


def test_excluded_kinds_cover_all_non_equity_types():
    """类型表的分类枚举与排除集合一致，新增类别时要同步。"""
    assert _EXCLUDED_KINDS == {"warrant", "unit", "right", "preferred", "note"}


def test_missing_type_file_excludes_nothing(tmp_path):
    """类型表缺失时不能一股脑全排掉（未知不作恶）。"""
    assert _load_non_common(tmp_path) == set()
    assert _load_non_common(None) == set()


# ── RS 倍数：几何相对强度 ───────────────────────────────────

def test_ratio_is_wealth_ratio_not_gain_ratio():
    """倍数 = (1+个股涨幅)/(1+基准涨幅)，即财富指数之比。"""
    assert _relative_strength(1.472, 0.1584) == pytest.approx(2.472 / 1.1584)


def test_ratio_stays_positive_when_stock_loses_and_market_gains():
    """旧口径这里是负数（-7.7% / +15.84% = -0.49），熊熊市场里符号会翻转。"""
    ratio = _relative_strength(-0.077, 0.1584)
    assert ratio > 0
    assert ratio == pytest.approx(0.923 / 1.1584)   # 0.797，读作「跑输大盘 20%」


def test_ratio_stays_positive_when_both_lose():
    """大盘 -10%、个股 -5% → 1.056，表示「跌得比大盘少」，符号不会反转成负数。"""
    assert _relative_strength(-0.05, -0.10) == pytest.approx(0.95 / 0.90)


def test_outperformer_always_scores_above_one():
    """无论涨跌市，涨得/跌得少的票倍数必须 > 1 —— 这是「相对强度」的核心不变式。"""
    for bench in (-0.30, -0.10, 0.0, 0.15, 0.60):
        for stock in (-0.50, -0.20, -0.05, 0.05, 0.30, 1.20):
            ratio = _relative_strength(stock, bench)
            if ratio is None:
                continue
            if stock > bench:
                assert ratio > 1.0, f"基准 {bench:+.0%} 个股 {stock:+.0%} 应 > 1，实得 {ratio}"
            else:
                assert ratio <= 1.0, f"基准 {bench:+.0%} 个股 {stock:+.0%} 应 ≤ 1，实得 {ratio}"


def test_ratio_none_when_benchmark_collapsed():
    """基准腰斩到 0 时分母失效，返回 None 而不是 inf。"""
    assert _relative_strength(0.5, -1.0) is None


def test_ratio_none_for_total_loss_or_bad_input():
    assert _relative_strength(-1.0, 0.2) is None      # 个股归零，数学退化
    assert _relative_strength(0.5, None) is None
    assert _relative_strength(None, 0.2) is None


# ── 退市 / 停牌过滤 ─────────────────────────────────────────

def _write_pkl(cache_dir, symbol, prices, start="2025-06-02"):
    """往缓存目录写一个 pkl 行情文件。"""
    idx = pd.date_range(start, periods=len(prices), freq="B", tz="UTC")
    make_close(prices).set_axis(idx).to_pickle(cache_dir / f"{symbol}.pkl")


@pytest.fixture
def live_cache(tmp_path):
    """缓存里有一只正常交易的股票、一只停更 3 个月的股票，基准 SPY 数据新鲜。"""
    fresh = make_series(300, 0.001)
    stale = make_series(300, 0.002)
    _write_pkl(tmp_path, "SPY", fresh)
    _write_pkl(tmp_path, "LIVE", fresh)
    # 末尾停更：只保留到 3 个月前
    _write_pkl(tmp_path, "DEAD", stale[:240], start="2024-09-02")
    return tmp_path


def test_stale_ticker_excluded_from_cross_section(live_cache):
    """停更超过 30 天的票（退市）不参与排名。"""
    result = compute_oneil_rs_map({}, cache_dir=live_cache)
    assert "LIVE" in result
    assert "DEAD" not in result


def test_fresh_ticker_outranks_pool(live_cache):
    """活跃股票仍在池中，且能拿到评级。"""
    result = compute_oneil_rs_map({}, cache_dir=live_cache)
    assert result["LIVE"][0] == 99


def test_stale_threshold_is_thirty_days():
    assert _STALE_DAYS == 30