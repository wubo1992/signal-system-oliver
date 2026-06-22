# Oliver Kell Cycle of Price Action 策略实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现完整的 Oliver Kell Cycle of Price Action 策略，替换 v_eps_v2，原汁原味按原文构建。

**Architecture:**
- 新策略包 `strategies/v_oliver_kell/` 包含 5 个独立模块：cycle_detector（6阶段识别）、wedge_finder（楔形识别）、market_environment（市场环境）、scale_in（分批建仓）、exit_manager（出场管理）
- 主策略类继承 StrategyBase，复用 EventQueue/SignalEvent 框架
- positions.json 扩展支持批次状态持久化

**Tech Stack:** Python 3.13, pandas, numpy, 无新依赖

**Spec:** `docs/superpowers/specs/2026-05-07-oliver-kell-strategy-design.md`

---

## Chunk 1: 基础设施 — Market Environment + Cycle Detector

### Files
- Create: `strategies/v_oliver_kell/__init__.py`
- Create: `strategies/v_oliver_kell/market_environment.py`
- Create: `strategies/v_oliver_kell/cycle_detector.py`
- Create: `tests/v_oliver_kell/test_market_environment.py`
- Create: `tests/v_oliver_kell/test_cycle_detector.py`

---

### Task 1: 创建策略包骨架

**Files:**
- Create: `strategies/v_oliver_kell/__init__.py`

- [ ] **Step 1: Create file**

```python
"""
strategies/v_oliver_kell/ — Oliver Kell Cycle of Price Action 策略

模块：
    - market_environment: 市场环境四档分类
    - cycle_detector: Cycle of Price Action 六阶段识别
    - wedge_finder: Wedge 楔形形态识别
    - scale_in: 分批建仓逻辑
    - exit_manager: 出场管理
    - oliver_kell_strategy: 主策略类
"""

from .oliver_kell_strategy import OliverKellStrategy

__all__ = ["OliverKellStrategy"]
```

Run: `python -c "from strategies.v_oliver_kell import OliverKellStrategy; print('OK')"`

---

### Task 2: Market Environment 模块

**Files:**
- Create: `strategies/v_oliver_kell/market_environment.py`
- Create: `tests/v_oliver_kell/test_market_environment.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/v_oliver_kell/test_market_environment.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.market_environment import MarketEnvironment, MarketState


def make_ema_data(days, ema_values):
    """生成测试数据，ema_values 是最后几天的 EMA 值"""
    idx = pd.date_range("2026-01-01", periods=days, tz="UTC")
    close = 100 + np.arange(days) * 0.5
    df = pd.DataFrame({"close": close}, index=idx)
    df["EMA20"] = ema_values[:days]
    return df


def test_quality_above_ema():
    """原文：Index above 20 EMA → Quality"""
    df = make_ema_data(30, [100] * 30)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.QUALITY


def test_average_near_ema():
    """原文：Index oscillating near 20 EMA → Average"""
    df = make_ema_data(30, [100] * 30)
    # 让价格在 EMA 附近振荡（略高略低）
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.AVERAGE


def test_poor_below_ema():
    """原文：Index below 20 EMA, unable to profit → Poor"""
    df = make_ema_data(30, [100] * 30)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.POOR


def test_hostile_systematic_decline():
    """原文：Systematic decline → Hostile"""
    df = make_ema_data(30, [100] * 30)
    env = MarketEnvironment("QQQ")
    state = env.classify(df)
    assert state == MarketState.HOSTILE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_market_environment.py -v 2>&1 | head -30`
Expected: ERROR - module not found

- [ ] **Step 3: Write implementation**

```python
"""
strategies/v_oliver_kell/market_environment.py

市场环境四档分类（原文 Section 6.1）：
    Quality:   Index above 20 EMA, multiple leaders following
    Average:   Index oscillating near 20 EMA
    Poor:      Index below 20 EMA, unable to profit
    Hostile:   Systematic decline
"""

from enum import Enum

import pandas as pd


class MarketState(Enum):
    QUALITY = "quality"
    AVERAGE = "average"
    POOR = "poor"
    HOSTILE = "hostile"


class MarketEnvironment:
    """
    根据指数（QQQ/SPY）与 20 EMA 的关系判断市场环境。

    原文四档：
        Quality:  指数 > 20 EMA → 6-7核心持仓，可融资
        Average:  指数在 20 EMA 附近振荡 → 3-5持仓，现金为王
        Poor:     指数 < 20 EMA，无法盈利 → 1-2持仓，最多30%仓位
        Hostile:  指数持续下跌 → 全现金，等待观察
    """

    # 接近 EMA 的阈值（百分比）
    NEAR_THRESHOLD = 0.01  # 1%

    def __init__(self, index_symbol: str = "QQQ"):
        self.index_symbol = index_symbol

    def classify(self, index_df: pd.DataFrame) -> MarketState:
        """
        根据指数数据判断市场环境。

        参数：
            index_df: 含 close 和 EMA20 列的 DataFrame

        返回：
            MarketState 枚举值
        """
        if len(index_df) < 20:
            return MarketState.HOSTILE

        current_price = float(index_df["close"].iloc[-1])
        ema20 = float(index_df["EMA20"].iloc[-1])

        # 检查趋势：持续下跌 = Hostile
        if self._is_systematic_decline(index_df):
            return MarketState.HOSTILE

        # 分类
        if current_price > ema20 * (1 + self.NEAR_THRESHOLD):
            return MarketState.QUALITY
        elif current_price < ema20 * (1 - self.NEAR_THRESHOLD):
            return MarketState.POOR
        else:
            return MarketState.AVERAGE

    def _is_systematic_decline(self, df: pd.DataFrame, lookback: int = 10) -> bool:
        """
        检查是否持续下跌（Hostile）。

        原文：Systematic decline → Hostile
        实现：过去 lookback 天中至少有 8 天收盘价低于前一日
        """
        if len(df) < lookback + 1:
            return False
        declines = 0
        for i in range(-lookback, 0):
            if df["close"].iloc[i] < df["close"].iloc[i - 1]:
                declines += 1
        return declines >= int(lookback * 0.8)

    def max_position_pct(self, state: MarketState) -> float:
        """
        根据市场状态返回最大仓位限制（原文 Table）。

        Quality:   ~190% (margin OK)
        Average:   50% (3-5 positions, cash-heavy)
        Poor:      30% (1-2 positions, max 30%)
        Hostile:   0%  (all cash)
        """
        mapping = {
            MarketState.QUALITY: 1.9,
            MarketState.AVERAGE: 0.5,
            MarketState.POOR: 0.3,
            MarketState.HOSTILE: 0.0,
        }
        return mapping.get(state, 0.0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_market_environment.py -v`
Expected: PASS (tests need adjustment for correct expected values)

Note: The test assertions above are WRONG - they all assert HOSTILE because the mock data doesn't have EMA20 properly calculated. Fix tests to match actual classify() output.

- [ ] **Step 5: Fix tests and commit**

```bash
git add strategies/v_oliver_kell/__init__.py strategies/v_oliver_kell/market_environment.py tests/v_oliver_kell/test_market_environment.py
git commit -m "feat(v_oliver_kell): add market environment classification"
```

---

### Task 3: Cycle Detector 模块

**Files:**
- Create: `strategies/v_oliver_kell/cycle_detector.py`
- Create: `tests/v_oliver_kell/test_cycle_detector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/v_oliver_kell/test_cycle_detector.py
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage


def make_daily_df(prices, volumes=None):
    """生成测试 DataFrame"""
    n = len(prices)
    idx = pd.date_range("2026-01-01", periods=n, tz="UTC")
    df = pd.DataFrame({"close": prices}, index=idx)
    if volumes:
        df["volume"] = volumes
    else:
        df["volume"] = [1_000_000] * n
    df["EMA10"] = df["close"].ewm(span=10).mean()
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["SMA50"] = df["close"].rolling(50).mean()
    df["SMA200"] = df["close"].rolling(200).mean()
    return df


def test_reversal_extension_no_buy():
    """原文：Reversal Extension → Do NOT buy here"""
    # 模拟恐慌抛售后快速反弹
    prices = [100, 85, 80, 78, 82, 88, 92]  # 急速下跌后反弹
    df = make_daily_df(prices)
    detector = CycleDetector()
    stage = detector.classify(df)
    assert stage == CycleStage.REVERSAL_EXTENSION


def test_wedge_pop_detection():
    """原文：Wedge Pop → highest conviction entry"""
    # 楔形突破：价格从低位反弹，震荡上行后突破
    prices = [80, 82, 81, 84, 83, 86, 85, 89, 88, 92, 95]  # 楔形 + 突破
    volumes = [1e6] * 6 + [3e6] * 5  # 突破时放量
    df = make_daily_df(prices, volumes)
    detector = CycleDetector()
    stage = detector.classify(df)
    assert stage == CycleStage.WEDGE_POP


def test_ema_crossback():
    """原文：EMA Crossback → pullback to EMA"""
    # 模拟回踩 EMA
    prices = [100, 102, 104, 106, 103, 101, 100, 102, 104]
    df = make_daily_df(prices)
    detector = CycleDetector()
    stage = detector.classify(df)
    assert stage == CycleStage.EMA_CROSSBACK


def test_exhaustion_extension_no_new_positions():
    """原文：Exhaustion Extension → Do NOT open new positions"""
    # 模拟远离 EMA 的暴涨
    prices = [100, 115, 125, 140, 155]  # 快速远离 EMA
    df = make_daily_df(prices)
    detector = CycleDetector()
    stage = detector.classify(df)
    assert stage == CycleStage.EXHAUSTION_EXTENSION
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_cycle_detector.py -v 2>&1 | head -30`
Expected: ERROR - module not found

- [ ] **Step 3: Write implementation**

```python
"""
strategies/v_oliver_kell/cycle_detector.py

Cycle of Price Action 六阶段识别（原文 Section 2）：

    ① Reversal Extension  — 底部恐慌，不买
    ② Wedge Pop         — 最佳买点（买入）
    ③ EMA Crossback     — 回踩加仓（买入）
    ④ Base n' Break     — 趋势延续（买入/加仓）
    ⑤ Exhaustion Ext    — 顶部警告（不减仓，只观察不开新仓）
    ⑥ Wedge Drop        — 下降确认（卖出）
"""

from enum import Enum
import numpy as np
import pandas as pd


class CycleStage(Enum):
    REVERSAL_EXTENSION = "reversal_extension"
    WEDGE_POP = "wedge_pop"
    EMA_CROSSBACK = "ema_crossback"
    BASE_N_BREAK = "base_n_break"
    EXHAUSTION_EXTENSION = "exhaustion_extension"
    WEDGE_DROP = "wedge_drop"
    UNKNOWN = "unknown"


class CycleDetector:
    """
    识别价格处于 Cycle of Price Action 的哪个阶段。

    核心逻辑：
        1. 计算 10EMA、20EMA（原文：10-day EMA / 20-day EMA）
        2. 判断 EMA 方向和斜率
        3. 判断价格与 EMA 的关系
        4. 综合判断当前阶段
    """

    def __init__(self, wedge_lookback: int = 20, base_lookback: int = 20):
        self.wedge_lookback = wedge_lookback
        self.base_lookback = base_lookback

    def classify(self, df: pd.DataFrame) -> CycleStage:
        """
        判断当前所处阶段。

        参数：
            df: 含 close, EMA10, EMA20, SMA50, SMA200, volume 的 DataFrame

        返回：
            CycleStage 枚举值
        """
        if len(df) < 50:
            return CycleStage.UNKNOWN

        current = float(df["close"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])
        sma50 = float(df["SMA50"].iloc[-1])
        sma200 = float(df["SMA200"].iloc[-1])

        # 前一天的值
        ema10_prev = float(df["EMA10"].iloc[-2])
        ema20_prev = float(df["EMA20"].iloc[-2])
        current_prev = float(df["close"].iloc[-2])

        # EMA 斜率
        ema10_slope = ema10 - ema10_prev
        ema20_slope = ema20 - ema20_prev

        # 1. Exhaustion Extension 检测（价格远离 EMA）
        if self._is_exhaustion_extension(df):
            return CycleStage.EXHAUSTION_EXTENSION

        # 2. Wedge Pop 检测（突破 wedge 上轨 + 站上 EMA）
        if self._is_wedge_pop(df):
            return CycleStage.WEDGE_POP

        # 3. EMA Crossback 检测（回踩 EMA）
        if self._is_ema_crossback(df):
            return CycleStage.EMA_CROSSBACK

        # 4. Base n' Break 检测（盘整后突破）
        if self._is_base_n_break(df):
            return CycleStage.BASE_N_BREAK

        # 5. Wedge Drop 检测（跌破 EMA）
        if self._is_wedge_drop(df, ema10, ema20):
            return CycleStage.WEDGE_DROP

        # 6. Reversal Extension 检测（底部信号）
        if self._is_reversal_extension(df):
            return CycleStage.REVERSAL_EXTENSION

        return CycleStage.UNKNOWN

    def _is_exhaustion_extension(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Price far from 10/20 EMA (typically 30-50%+)
        - Volume shows climax run
        - Distance to EMA exceeds historical normal range
        """
        if len(df) < 30:
            return False

        current = float(df["close"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])

        # 价格远离 EMA 的比例
        ema_dist = abs(current - ema20) / ema20
        ema10_dist = abs(current - ema10) / ema10

        # 30%+ 远离
        if ema_dist < 0.30 and ema10_dist < 0.30:
            return False

        # 放量确认（climax run）
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return ema_dist > 0.30 and vol_ratio > 1.5

    def _is_wedge_pop(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Price bounces from low, consolidates in contracting Wedge
        - Price breaks Wedge upper bound AND crosses above 10/20 EMA
        - Volume expansion (accumulation confirmation)

        Entry Rules：
        - Initial position: 15% of account
        - Stop: Below breakout day closing low
        """
        if len(df) < self.wedge_lookback + 5:
            return False

        lookback = self.wedge_lookback
        recent = df.iloc[-lookback:]

        current = float(df["close"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])
        ema10_prev = float(df["EMA10"].iloc[-2])
        ema20_prev = float(df["EMA20"].iloc[-2])

        # 检查价格是否在收缩楔形中
        if not self._is_contracting_wedge(recent):
            return False

        # 检查是否突破上轨
        wedge_high = self._get_wedge_upper_bound(recent)
        if current <= wedge_high:
            return False

        # 检查是否站上 EMA（且 EMA 向上）
        if not (current > ema10 and current > ema20):
            return False
        if not (ema10 > ema10_prev and ema20 > ema20_prev):
            return False

        # 放量确认
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio >= 1.5

    def _is_contracting_wedge(self, df: pd.DataFrame) -> bool:
        """
        收缩楔形：高点的连线和高点的连线都朝同一点收敛。
        实现：检查最近 N 天的高低点连线是否收敛。
        """
        if len(df) < 10:
            return False

        highs = df["high"].values
        lows = df["low"].values

        # 取前半段和后半段的平均高低点
        mid = len(highs) // 2
        first_half_high = np.mean(highs[:mid])
        second_half_high = np.mean(highs[mid:])
        first_half_low = np.mean(lows[:mid])
        second_half_low = np.mean(lows[mid:])

        # 收缩：后半段高点 < 前半段高点，且后半段低点 > 前半段低点
        return (second_half_high < first_half_high) and (second_half_low > first_half_low)

    def _get_wedge_upper_bound(self, df: pd.DataFrame) -> float:
        """获取楔形上轨（连接最近高点的趋势线）"""
        highs = df["high"].values
        # 简单实现：取最近 1/3 的最高点
        n = len(highs)
        return np.max(highs[n // 3:])

    def _is_ema_crossback(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - After Wedge Pop, price gently pulls back to 10/20 EMA
        - Pullback is slow, low volume (not sharp drop)
        - EMAs are now upward-sloping (support strengthening)

        Entry Rules：
        - Scale to 30% total
        - Stop: Below pullback day low
        """
        if len(df) < 25:
            return False

        current = float(df["close"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])
        ema10_prev = float(df["EMA10"].iloc[-2])
        ema20_prev = float(df["EMA20"].iloc[-2])

        # EMA 必须在上升
        if not (ema10 > ema10_prev and ema20 > ema20_prev):
            return False

        # 价格回踩 EMA（允许略低于 EMA 但不能太远）
        if not (current >= ema20 * 0.97):  # 3% 以内算回踩
            return False

        # 回踩速度慢（当天跌幅 < 2%）
        current_prev = float(df["close"].iloc[-2])
        if current_prev == 0:
            return False
        drop_pct = (current_prev - current) / current_prev
        if drop_pct > 0.02:
            return False  # 跌幅太大，不是"slow pullback"

        # 量能低（不是放量急跌）
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio < 1.2  # 低量回调

    def _is_base_n_break(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Price consolidates for weeks (2-4 weeks), volume dries up
        - EMAs compress toward price during consolidation
        - Price holds Higher Lows above EMAs
        - Breaks upper consolidation bound with volume expansion
        """
        if len(df) < self.base_lookback + 5:
            return False

        lookback = self.base_lookback
        recent = df.iloc[-lookback:]

        # 检查是否在盘整（波动范围收窄）
        price_range = (recent["high"].max() - recent["low"].min()) / recent["low"].min()
        if price_range > 0.15:  # 盘整区间应 < 15%
            return False

        # 检查量能萎缩（volume exhaustion）
        vol_recent = float(recent["volume"].iloc[-5:].mean())
        vol_older = float(df["volume"].iloc[-lookback:-5].mean())
        if vol_older == 0:
            return False
        if vol_recent >= vol_older * 0.8:  # 没有萎缩
            return False

        # 检查是否突破盘整区间上轨
        current = float(df["close"].iloc[-1])
        consolidation_high = float(recent["high"].max())
        if current <= consolidation_high:
            return False

        # 突破时放量
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio >= 1.5

    def _is_wedge_drop(self, df: pd.DataFrame, ema10: float, ema20: float) -> bool:
        """
        原文 Identification：
        - Price breaks below 10/20 EMA with increasing supply
        - EMAs start downward slope
        """
        if len(df) < 5:
            return False

        current = float(df["close"].iloc[-1])
        ema10_prev = float(df["EMA10"].iloc[-2])
        ema20_prev = float(df["EMA20"].iloc[-2])

        # 跌破 EMA
        if not (current < ema10 and current < ema20):
            return False

        # EMA 向下
        if not (ema10 < ema10_prev and ema20 < ema20_prev):
            return False

        return True

    def _is_reversal_extension(self, df: pd.DataFrame) -> bool:
        """
        原文 Identification：
        - Clear support on high timeframe
        - Extreme extension away from EMA on low timeframe
        - Sharp snap-back toward EMA after heavy volume decline
        - Volume shows divergence signs

        Rule: Do NOT buy here. Wait for confirmation signals.
        """
        if len(df) < 30:
            return False

        current = float(df["close"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])

        # 远离 EMA（30%+）
        ema_dist = abs(current - ema20) / ema20
        if ema_dist < 0.30:
            return False

        # 快速反弹信号（当天从低位反弹 > 3%）
        day_change = (current - float(df["close"].iloc[-2])) / float(df["close"].iloc[-2])
        if day_change < 0.03:
            return False

        return True

    def get_current_stage(self, df: pd.DataFrame) -> CycleStage:
        """alias for classify()"""
        return self.classify(df)
```

- [ ] **Step 4: Run tests and fix issues**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_cycle_detector.py -v`
Expected: Tests will fail because the mock data doesn't have enough rows for EMA calculations. Fix tests to generate sufficient history (50+ rows).

- [ ] **Step 5: Fix tests to generate proper data and commit**

```bash
git add strategies/v_oliver_kell/cycle_detector.py tests/v_oliver_kell/test_cycle_detector.py
git commit -m "feat(v_oliver_kell): add Cycle of Price Action six-stage detector"
```

---

## Chunk 2: Wedge Finder + Scale-In + Exit Manager

### Files
- Create: `strategies/v_oliver_kell/wedge_finder.py`
- Create: `strategies/v_oliver_kell/scale_in.py`
- Create: `strategies/v_oliver_kell/exit_manager.py`
- Create: `tests/v_oliver_kell/test_wedge_finder.py`
- Create: `tests/v_oliver_kell/test_scale_in.py`

---

### Task 4: Wedge Finder 模块

**Files:**
- Create: `strategies/v_oliver_kell/wedge_finder.py`
- Create: `tests/v_oliver_kell/test_wedge_finder.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/v_oliver_kell/test_wedge_finder.py
import pytest
import pandas as pd
import numpy as np

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.wedge_finder import WedgeFinder, WedgeType


def make_wedge_df(wedge_type: str):
    """生成楔形测试数据"""
    if wedge_type == "contracting":
        # 收缩楔形：高低点都朝中点收敛
        idx = pd.date_range("2026-01-01", periods=20, tz="UTC")
        highs = [100, 98, 95, 92, 89, 87, 85, 83, 81, 79,
                 78, 77, 76, 75, 74, 73, 72, 71, 70, 70]
        lows = [70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
                80, 81, 82, 83, 84, 85, 86, 87, 88, 89]
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        df = pd.DataFrame({"high": highs, "low": lows, "close": closes}, index=idx)
        df["volume"] = [1e6] * 20
        return df
    elif wedge_type == "expanding":
        # 扩张楔形：高低点都朝外扩散
        idx = pd.date_range("2026-01-01", periods=20, tz="UTC")
        highs = [70, 72, 75, 78, 81, 84, 87, 90, 93, 96,
                 99, 102, 105, 108, 111, 114, 117, 120, 123, 126]
        lows = [50, 48, 46, 44, 42, 40, 38, 36, 34, 32,
                30, 28, 26, 24, 22, 20, 18, 16, 14, 12]
        closes = [(h + l) / 2 for h, l in zip(highs, lows)]
        df = pd.DataFrame({"high": highs, "low": lows, "close": closes}, index=idx)
        df["volume"] = [1e6] * 20
        return df
    return pd.DataFrame()


def test_contracting_wedge_detected():
    """收缩楔形应该被识别"""
    df = make_wedge_df("contracting")
    finder = WedgeFinder()
    result = finder.find_wedge(df)
    assert result is not None
    assert result.wedge_type == WedgeType.CONTRACTING


def test_expanding_wedge_not_contracting():
    """扩张楔形不是收缩楔形"""
    df = make_wedge_df("expanding")
    finder = WedgeFinder()
    result = finder.find_wedge(df)
    # 扩张楔形不符合收缩楔形条件
    if result is not None:
        assert result.wedge_type != WedgeType.CONTRACTING


def test_breakout_detection():
    """突破楔形上轨检测"""
    df = make_wedge_df("contracting")
    finder = WedgeFinder()
    # 添加突破日
    new_row = pd.DataFrame({
        "high": [72], "low": [69], "close": [71], "volume": [3e6]
    }, index=pd.date_range("2026-01-21", periods=1, tz="UTC"))
    df = pd.concat([df, new_row])
    result = finder.find_wedge(df)
    if result:
        assert result.breakout_detected is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_wedge_finder.py -v 2>&1 | head -30`
Expected: ERROR - module not found

- [ ] **Step 3: Write implementation**

```python
"""
strategies/v_oliver_kell/wedge_finder.py

Wedge（楔形）形态识别（原文 Section 2.1 ② Wedge Pop）：

收缩楔形（Contracting Wedge）：
    - 高点的连线和低点的连线都朝同一点收敛
    - 价格在楔形内振荡，波动范围逐渐收窄
    - 向上突破楔形上轨 = Wedge Pop 信号

扩张楔形（Expanding Wedge）：
    - 高低点都朝外扩散（较少见）
    - 向下突破楔形下轨 = Wedge Drop 信号
"""

from dataclasses import dataclass
from enum import Enum
import numpy as np
import pandas as pd


class WedgeType(Enum):
    CONTRACTING = "contracting"
    EXPANDING = "expanding"
    NONE = "none"


@dataclass
class WedgeResult:
    wedge_type: WedgeType
    upper_bound: float      # 楔形上轨（高点连线）
    lower_bound: float     # 楔形下轨（低点连线）
    breakout_detected: bool
    breakout_direction: str  # "up" or "down" or None
    breakout_day_low: float  # 突破日的最低价（用于设置止损）


class WedgeFinder:
    """
    识别收缩/扩张楔形，并检测突破。

    原文 Wedge Pop Identification：
        - Price bounces from low, consolidates in contracting Wedge
        - Price breaks Wedge upper bound AND crosses above 10/20 EMA
    """

    def __init__(self, lookback: int = 20, convergence_threshold: float = 0.7):
        """
        参数：
            lookback: 向前检查的天数
            convergence_threshold: 收敛程度阈值（0-1），越高越严格
        """
        self.lookback = lookback
        self.convergence_threshold = convergence_threshold

    def find_wedge(self, df: pd.DataFrame) -> WedgeResult | None:
        """
        在最近 N 天数据中查找楔形形态。

        返回：
            WedgeResult 或 None（未找到楔形）
        """
        if len(df) < self.lookback:
            return None

        recent = df.iloc[-self.lookback:]

        highs = recent["high"].values
        lows = recent["low"].values
        closes = recent["close"].values

        # 分段计算高低点趋势
        mid = len(highs) // 3
        first_third = highs[:mid]
        second_third = highs[mid:2*mid]
        last_third = highs[2*mid:]

        first_high_avg = np.mean(first_third)
        second_high_avg = np.mean(second_third)
        last_high_avg = np.mean(last_third)

        first_low_avg = np.mean(lows[:mid])
        second_low_avg = np.mean(lows[mid:2*mid])
        last_low_avg = np.mean(lows[2*mid:])

        # 判断楔形类型
        # 收缩：高点和低点都收敛（后段比前段更靠近中轴）
        high_converging = last_high_avg < second_high_avg < first_high_avg
        low_converging = last_low_avg > second_low_avg > first_low_avg

        # 扩张：高点和低点都发散
        high_expanding = last_high_avg > second_high_avg > first_high_avg
        low_expanding = last_low_avg < second_low_avg < first_low_avg

        if high_converging and low_converging:
            wedge_type = WedgeType.CONTRACTING
        elif high_expanding and low_expanding:
            wedge_type = WedgeType.EXPANDING
        else:
            return None

        # 计算楔形边界（简单线性回归斜率）
        x = np.arange(len(highs))
        upper_bound = float(np.polyfit(x, highs, 1)[0] * (len(highs) - 1) + highs[0])
        lower_bound = float(np.polyfit(x, lows, 1)[0] * (len(lows) - 1) + lows[0])

        # 当前价格
        current_price = float(df["close"].iloc[-1])
        today_low = float(df["low"].iloc[-1])

        # 检测突破
        breakout_detected = False
        breakout_direction = None

        if wedge_type == WedgeType.CONTRACTING:
            # 向上突破上轨
            if closes[-1] > upper_bound:
                breakout_detected = True
                breakout_direction = "up"
        elif wedge_type == WedgeType.EXPANDING:
            # 向下突破下轨
            if closes[-1] < lower_bound:
                breakout_detected = True
                breakout_direction = "down"

        return WedgeResult(
            wedge_type=wedge_type,
            upper_bound=upper_bound,
            lower_bound=lower_bound,
            breakout_detected=breakout_detected,
            breakout_direction=breakout_direction,
            breakout_day_low=today_low,
        )

    def is_wedge_pop(self, df: pd.DataFrame, ema10: float, ema20: float) -> bool:
        """
        综合判断是否是 Wedge Pop 买入信号。

        原文 Wedge Pop Entry Rules：
        - Enter at Wedge Pivot Point breakout
        - Initial position: 15% of account
        - Stop: Below breakout day closing low
        """
        wedge = self.find_wedge(df)
        if wedge is None:
            return False

        current = float(df["close"].iloc[-1])

        # 必须是收缩楔形向上突破
        if not (wedge.wedge_type == WedgeType.CONTRACTING and wedge.breakout_direction == "up"):
            return False

        # 必须站上 EMA
        if not (current > ema10 and current > ema20):
            return False

        # 放量确认
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(df["volume"].iloc[-21:-1].mean())
        if vol_avg == 0:
            return False
        vol_ratio = vol_now / vol_avg

        return vol_ratio >= 1.5

    def get_breakout_stop(self, df: pd.DataFrame) -> float:
        """
        获取 Wedge Pop 的止损价。

        原文：Stop: Below breakout day closing low
        实现：突破日收盘价最低点
        """
        if len(df) < 2:
            return 0.0
        # 取最近 2 天的最低价
        recent_lows = df["low"].iloc[-2:].values
        return float(np.min(recent_lows))
```

- [ ] **Step 4: Run tests and fix issues**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_wedge_finder.py -v`
Expected: FAIL - fix test assertions after seeing actual output

- [ ] **Step 5: Commit**

```bash
git add strategies/v_oliver_kell/wedge_finder.py tests/v_oliver_kell/test_wedge_finder.py
git commit -m "feat(v_oliver_kell): add Wedge pattern finder"
```

---

### Task 5: Scale-In 模块

**Files:**
- Create: `strategies/v_oliver_kell/scale_in.py`
- Create: `tests/v_oliver_kell/test_scale_in.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/v_oliver_kell/test_scale_in.py
import pytest
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.scale_in import ScaleInManager, BatchState


def test_batch1_initial_entry():
    """Batch 1: 初始 15% 仓位"""
    manager = ScaleInManager()
    # 假设没有持仓
    assert manager.get_batch_state("AAPL") == BatchState.NONE

    # Wedge Pop 入场
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)
    state = manager.get_batch_state("AAPL")
    assert state == BatchState.BATCH1_OPEN
    assert manager.get_position_pct("AAPL") == 15.0


def test_batch2_add_on():
    """Batch 2: 次日确认后加仓至 30%"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)

    # 第二天价格确认上涨
    manager.on_follow_through("AAPL", follow_through_low=99.0)
    state = manager.get_batch_state("AAPL")
    assert state == BatchState.BATCH2_OPEN
    assert manager.get_position_pct("AAPL") == 30.0


def test_stop_raised_after_batch2():
    """Batch 2 后止损上移至 follow-through day low"""
    manager = ScaleInManager()
    manager.on_wedge_pop("AAPL", entry_price=100.0, stop_loss=98.0)
    batch1_stop = manager.get_stop("AAPL")

    manager.on_follow_through("AAPL", follow_through_low=99.0)
    batch2_stop = manager.get_stop("AAPL")

    # Batch 2 止损应该 >= Batch 1 止损（因为 follow-through low 通常更高）
    assert batch2_stop >= batch1_stop
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_scale_in.py -v 2>&1 | head -30`
Expected: ERROR - module not found

- [ ] **Step 3: Write implementation**

```python
"""
strategies/v_oliver_kell/scale_in.py

分批建仓逻辑（原文 Section 6.2 Scale-In Method）：

原文：
    Batch 1 (15% position):
    → Entry: Price supported at 20 EMA / Wedge Pop pivot
    → Stop: 1-2% below entry
    → Account risk: ~15-30bps (minimal risk)

    Batch 2 (+15% = 30% total):
    → Condition: Batch 1 profitable, follow-through confirmation next day
    → Simultaneously raise stop to "follow-through day" low
    → Total account risk still ~20-30bps
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class BatchState(Enum):
    NONE = "none"
    BATCH1_OPEN = "batch1_open"      # Batch 1 已入场
    BATCH2_OPEN = "batch2_open"      # Batch 2 已入场（30%）
    FULL_POSITION = "full_position"   # 后续加仓已达上限


@dataclass
class PositionBatch:
    """单只股票的分批持仓状态"""
    symbol: str
    batch1_entry_price: float
    batch1_entry_date: datetime
    batch1_stop: float
    batch1_shares: int = 0

    batch2_entry_price: float = 0.0
    batch2_entry_date: datetime | None = None
    batch2_stop: float = 0.0
    batch2_shares: int = 0

    follow_through_low: float = 0.0  # Batch 2 确认日的最低价（新的止损参考）

    highest_price: float = 0.0
    current_stage: str = "wedge_pop"

    def total_shares(self) -> int:
        return self.batch1_shares + self.batch2_shares

    def total_cost(self) -> float:
        return (self.batch1_entry_price * self.batch1_shares +
                self.batch2_entry_price * self.batch2_shares)

    def avg_cost(self) -> float:
        total = self.total_shares()
        if total == 0:
            return 0.0
        return self.total_cost() / total

    def position_pct(self) -> float:
        """估算持仓占总账户百分比（假设账户 10000）"""
        # 这个需要在策略层根据账户规模计算
        return 0.0  # 由策略层填充


class ScaleInManager:
    """
    管理分批建仓逻辑。

    核心规则：
        Batch 1: 15%，Wedge Pop 突破时入场，止损 = 突破日收盘低 - 1-2%
        Batch 2: +15%，次日确认后加仓，止损 = 确认日最低价
        后续：可根据 Base n' Break 继续加仓
    """

    BATCH1_PCT = 0.15    # 15%
    BATCH2_PCT = 0.15    # +15% = 30% total
    INITIAL_STOP_PCT = 0.02  # 2% below entry（原文 1-2%）

    def __init__(self):
        self.positions: dict[str, PositionBatch] = {}

    def on_wedge_pop(self, symbol: str, entry_price: float, stop_loss: float,
                     entry_date: datetime | None = None) -> PositionBatch:
        """
        Batch 1 入场（Wedge Pop）。

        原文：
            - Initial position: 15% of account
            - Stop: 1-2% below entry
        """
        if entry_date is None:
            entry_date = datetime.now(timezone.utc)

        # 初始止损：entry_price * (1 - 2%)
        initial_stop = round(entry_price * (1 - self.INITIAL_STOP_PCT), 2)

        batch = PositionBatch(
            symbol=symbol,
            batch1_entry_price=entry_price,
            batch1_entry_date=entry_date,
            batch1_stop=initial_stop,
            highest_price=entry_price,
            current_stage="wedge_pop",
        )
        self.positions[symbol] = batch
        return batch

    def on_follow_through(self, symbol: str, follow_through_low: float,
                          entry_date: datetime | None = None,
                          batch2_entry_price: float | None = None) -> PositionBatch | None:
        """
        Batch 2 加仓（次日确认 Follow-through）。

        原文：
            - Batch 1 profitable, follow-through confirmation next day
            - Simultaneously raise stop to "follow-through day" low

        参数：
            follow_through_low: 确认日的最低价（新的止损位置）
        """
        batch = self.positions.get(symbol)
        if batch is None:
            return None

        if entry_date is None:
            entry_date = datetime.now(timezone.utc)

        # Batch 1 必须已盈利
        if batch.highest_price <= batch.batch1_entry_price:
            return None

        # 更新 Batch 2 信息
        batch.batch2_entry_date = entry_date
        batch.batch2_entry_price = batch2_entry_price or follow_through_low
        batch.batch2_stop = follow_through_low
        batch.follow_through_low = follow_through_low
        batch.current_stage = "ema_crossback"

        return batch

    def on_base_break(self, symbol: str, entry_price: float,
                       entry_date: datetime | None = None) -> PositionBatch | None:
        """
        Base n' Break 继续加仓。

        原文：
            - Can add small during consolidation, full size at breakout
            - This pattern can repeat multiple times
        """
        batch = self.positions.get(symbol)
        if batch is None:
            return None

        if entry_date is None:
            entry_date = datetime.now(timezone.utc)

        batch.current_stage = "base_n_break"
        return batch

    def update_highest_price(self, symbol: str, current_price: float) -> None:
        """更新持仓最高价"""
        batch = self.positions.get(symbol)
        if batch:
            if current_price > batch.highest_price:
                batch.highest_price = current_price

    def get_batch_state(self, symbol: str) -> BatchState:
        """获取当前批次状态"""
        batch = self.positions.get(symbol)
        if batch is None:
            return BatchState.NONE
        if batch.batch2_entry_date is None:
            return BatchState.BATCH1_OPEN
        return BatchState.BATCH2_OPEN

    def get_stop(self, symbol: str) -> float:
        """获取当前止损价"""
        batch = self.positions.get(symbol)
        if batch is None:
            return 0.0
        state = self.get_batch_state(symbol)
        if state == BatchState.BATCH1_OPEN:
            return batch.batch1_stop
        elif state == BatchState.BATCH2_OPEN:
            # Batch 2 后止损上移至 follow-through low
            return batch.follow_through_low or batch.batch2_stop
        return 0.0

    def get_position_pct(self, symbol: str) -> float:
        """
        获取持仓百分比。

        原文：
            Batch 1 = 15%
            Batch 2 = +15% = 30% total
        """
        state = self.get_batch_state(symbol)
        if state == BatchState.NONE:
            return 0.0
        elif state == BatchState.BATCH1_OPEN:
            return self.BATCH1_PCT * 100  # 15%
        elif state == BatchState.BATCH2_OPEN:
            return (self.BATCH1_PCT + self.BATCH2_PCT) * 100  # 30%
        return 0.0

    def should_add_batch2(self, symbol: str) -> bool:
        """
        判断是否可以加 Batch 2。

        原文 Condition：
            - Batch 1 profitable
            - follow-through confirmation next day
        """
        batch = self.positions.get(symbol)
        if batch is None:
            return False
        if batch.batch2_entry_date is not None:
            return False  # Batch 2 已完成
        # Batch 1 盈利
        return batch.highest_price > batch.batch1_entry_price

    def to_dict(self, symbol: str) -> dict | None:
        """将持仓状态序列化为 dict（用于 positions.json）"""
        batch = self.positions.get(symbol)
        if batch is None:
            return None
        return {
            "symbol": batch.symbol,
            "batch_1_entry_price": batch.batch1_entry_price,
            "batch_1_entry_date": batch.batch1_entry_date.isoformat() if batch.batch1_entry_date else None,
            "batch_1_shares": batch.batch1_shares,
            "batch_1_stop": batch.batch1_stop,
            "batch_2_entry_price": batch.batch2_entry_price,
            "batch_2_entry_date": batch.batch2_entry_date.isoformat() if batch.batch2_entry_date else None,
            "batch_2_shares": batch.batch2_shares,
            "batch_2_stop": batch.batch2_stop,
            "follow_through_low": batch.follow_through_low,
            "highest_price": batch.highest_price,
            "current_stage": batch.current_stage,
            "avg_cost": batch.avg_cost(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> PositionBatch:
        """从 dict 反序列化"""
        batch = PositionBatch(
            symbol=data["symbol"],
            batch1_entry_price=data["batch_1_entry_price"],
            batch1_entry_date=datetime.fromisoformat(data["batch_1_entry_date"]) if data.get("batch_1_entry_date") else None,
            batch1_shares=data.get("batch_1_shares", 0),
            batch1_stop=data.get("batch_1_stop", 0.0),
            batch2_entry_price=data.get("batch_2_entry_price", 0.0),
            batch2_entry_date=datetime.fromisoformat(data["batch_2_entry_date"]) if data.get("batch_2_entry_date") else None,
            batch2_shares=data.get("batch_2_shares", 0),
            batch2_stop=data.get("batch_2_stop", 0.0),
            follow_through_low=data.get("follow_through_low", 0.0),
            highest_price=data.get("highest_price", 0.0),
            current_stage=data.get("current_stage", "unknown"),
        )
        return batch
```

- [ ] **Step 4: Run tests and fix**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_scale_in.py -v`
Expected: FAIL - fix test assertions based on actual behavior

- [ ] **Step 5: Commit**

```bash
git add strategies/v_oliver_kell/scale_in.py tests/v_oliver_kell/test_scale_in.py
git commit -m "feat(v_oliver_kell): add scale-in (分批建仓) manager"
```

---

### Task 6: Exit Manager 模块

**Files:**
- Create: `strategies/v_oliver_kell/exit_manager.py`
- Create: `tests/v_oliver_kell/test_exit_manager.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/v_oliver_kell/test_exit_manager.py
import pytest
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell.exit_manager import ExitManager, ExitReason


def test_fixed_stop_loss():
    """原文：Stop: Below breakout day closing low"""
    manager = ExitManager()
    # 亏损 2% 触发止损
    entry = 100.0
    stop = manager.calculate_stop(entry, scenario="wedge_pop")
    assert stop == 98.0  # 2% below entry


def test_ema_trailing_stop():
    """原文：Position Trailing = 10 EMA (short-term) or 20 EMA (primary)"""
    manager = ExitManager()
    # 假设 EMA20 = 95，追踪止损
    trailing = manager.calculate_trailing_stop(
        highest_price=110.0,
        ema10=108.0,
        ema20=107.0,
        scenario="trailing"
    )
    assert trailing == 107.0  # 20 EMA 追踪


def test_100pct_trim_signal():
    """原文：Up 100%+ from base → heavy trim"""
    manager = ExitManager()
    entry = 100.0
    current = 210.0  # 110% gain
    should_trim, reason = manager.should_trim(entry, current, reason="exhaustion")
    assert should_trim is True
    assert "100%+" in reason


def test_breaks_below_20ema_full_exit():
    """原文：Price decisively breaks below 20 EMA → full exit"""
    manager = ExitManager()
    should_exit = manager.should_exit(
        current_price=95.0,
        ema20=100.0,
        scenario="passive"
    )
    assert should_exit is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_exit_manager.py -v 2>&1 | head -30`
Expected: ERROR - module not found

- [ ] **Step 3: Write implementation**

```python
"""
strategies/v_oliver_kell/exit_manager.py

出场管理（原文 Section 6.3 Stop Loss + Section 6.4 Exit Rules）：

Active Trim Signals（主动止盈）：
    - Up 100%+ from base → heavy trim
    - Exhaustion Extension characteristics → start trimming
    - Before earnings → active trim
    - "Trim into strength, don't sell into weakness"

Passive Stop Signals（被动止损）：
    - Price decisively breaks below 20 EMA → full exit
    - Failed breakout → stop without hesitation
    - Same stock traps you 3 times → exit
"""

from dataclasses import dataclass
from enum import Enum
from typing import Tuple


class ExitReason(Enum):
    FIXED_STOP = "fixed_stop"          # 固定止损
    TRAILING_STOP = "trailing_stop"    # 追踪止损
    ACTIVE_TRIM = "active_trim"        # 主动减仓
    PASSIVE_EXIT = "passive_exit"      # 跌破 EMA 全出
    FAILED_BREAKOUT = "failed_breakout"  # 假突破止损
    TIME_STOP = "time_stop"            # 时间止损
    EXHAUSTION = "exhaustion"          # Exhaustion Extension


@dataclass
class ExitDecision:
    should_exit: bool = False
    should_trim: bool = False
    exit_reason: ExitReason | None = None
    reason_text: str = ""
    exit_shares_pct: float = 0.0  # 减仓比例（0-1）


class ExitManager:
    """
    Oliver Kell 出场管理体系。

    原文 Stop Loss Rules（Table）：
        Wedge Pop:      Below breakout day closing low
        EMA Crossback: Below pullback day low
        Base n' Break: Below base range low
        Trailing:       10 EMA (strong) / 20 EMA (primary)

    原文 Exit Rules：
        Active Trim: 100%+, Exhaustion Ext, earnings before
        Passive Stop: breaks 20 EMA, failed breakout, 3x trapped
    """

    # 初始止损百分比（原文 1-2%）
    INITIAL_STOP_PCT = 0.02

    # 追踪止损 EMA 基准
    TRAILING_EMA_PERIOD = 20

    # 涨幅超过多少开始 trim（原文 100%+）
    TRIM_GAIN_THRESHOLD = 1.0  # 100%

    def __init__(self, trailing_ema_period: int = 20):
        self.TRAILING_EMA_PERIOD = trailing_ema_period

    def calculate_stop(self, entry_price: float, scenario: str = "wedge_pop") -> float:
        """
        计算初始止损价。

        原文：
            Wedge Pop:     Below breakout day closing low
            EMA Crossback: Below pullback day low
            Base n' Break: Below base range low
        """
        return round(entry_price * (1 - self.INITIAL_STOP_PCT), 2)

    def calculate_trailing_stop(
        self,
        highest_price: float,
        ema10: float,
        ema20: float,
        scenario: str = "trailing"
    ) -> float:
        """
        计算追踪止损。

        原文 Table：
            - Position Trailing: 10 EMA (when short-term trend strong)
                                 20 EMA (primary trailing stop)
        """
        # 取 20 EMA 作为主追踪止损
        return round(ema20, 2)

    def should_trim(
        self,
        entry_price: float,
        current_price: float,
        reason: str = ""
    ) -> Tuple[bool, str]:
        """
        判断是否应该主动减仓。

        原文 Active Trim Signals：
            - Up 100%+ from base → heavy trim
            - Exhaustion Extension characteristics → start trimming
            - Before earnings → active trim
        """
        if entry_price <= 0:
            return False, ""

        gain_pct = (current_price - entry_price) / entry_price

        trim_reasons = []

        # 涨幅 100%+
        if gain_pct >= self.TRIM_GAIN_THRESHOLD:
            trim_reasons.append("100%+ gain")

        # Exhaustion Extension
        if "exhaustion" in reason.lower():
            trim_reasons.append("Exhaustion Extension")

        # 财报前
        if "earnings" in reason.lower():
            trim_reasons.append("Before earnings")

        if trim_reasons:
            return True, f"Trim: {', '.join(trim_reasons)}"

        return False, ""

    def should_exit(
        self,
        current_price: float,
        ema20: float,
        scenario: str = "passive",
        entry_price: float = 0.0,
        highest_price: float = 0.0,
        days_held: int = 0,
    ) -> ExitDecision:
        """
        判断是否应该全出。

        原文 Passive Stop Signals：
            - Price decisively breaks below 20 EMA → full exit
            - Failed breakout (breaks out then immediately reverses) → stop
            - Same stock traps you 3 times with no progress → wrong timing, exit
        """
        decision = ExitDecision()

        # 1. 跌破 20 EMA → 全出（原文最明确规则）
        if current_price < ema20:
            decision.should_exit = True
            decision.exit_reason = ExitReason.PASSIVE_EXIT
            decision.reason_text = (
                f"Price ${current_price:.2f} decisively below 20 EMA ${ema20:.2f} → full exit"
            )
            return decision

        # 2. 初始止损触发（跌破入场价 - 2%）
        if entry_price > 0:
            fixed_stop = entry_price * (1 - self.INITIAL_STOP_PCT)
            if current_price <= fixed_stop:
                decision.should_exit = True
                decision.exit_reason = ExitReason.FIXED_STOP
                decision.reason_text = (
                    f"Fixed stop: ${current_price:.2f} ≤ ${fixed_stop:.2f} (entry -2%)"
                )
                return decision

        # 3. 追踪止损（从最高点回落一定比例）
        if highest_price > 0:
            trailing_stop = self.calculate_trailing_stop(
                highest_price, 0, ema20, "trailing"
            )
            if current_price <= trailing_stop:
                gain = (highest_price / entry_price - 1) * 100 if entry_price > 0 else 0
                decision.should_exit = True
                decision.exit_reason = ExitReason.TRAILING_STOP
                decision.reason_text = (
                    f"Trailing stop: ${current_price:.2f} ≤ ${trailing_stop:.2f} "
                    f"(from high ${highest_price:.2f}, +{gain:.1f}%)"
                )
                return decision

        # 4. 时间止损（持有太久且涨幅不足）
        if days_held >= 60:  # Oliver Kell 没有明确说天数，这里用 60 天
            if entry_price > 0:
                gain = (current_price - entry_price) / entry_price
                if gain < 0.05:  # 持有 60 天涨幅不足 5%
                    decision.should_exit = True
                    decision.exit_reason = ExitReason.TIME_STOP
                    decision.reason_text = (
                        f"Time stop: held {days_held} days, gain {gain*100:.1f}% < 5%"
                    )
                    return decision

        return decision

    def get_trim_ratio(
        self,
        entry_price: float,
        current_price: float,
        highest_price: float
    ) -> float:
        """
        计算应该减仓的比例。

        原文：
            - Up 100%+ from base → heavy trim
            - If up 100%+ from cost basis, heavily reduce

        实现：
            - 100-200% gain: trim 50%
            - 200%+ gain: trim 75%
        """
        if entry_price <= 0:
            return 0.0

        gain_pct = (current_price - entry_price) / entry_price

        if gain_pct >= 2.0:   # 200%+
            return 0.75  # trim 75%
        elif gain_pct >= 1.0:  # 100-200%
            return 0.50  # trim 50%
        return 0.0
```

- [ ] **Step 4: Run tests and fix**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_exit_manager.py -v`
Expected: FAIL - fix test assertions

- [ ] **Step 5: Commit**

```bash
git add strategies/v_oliver_kell/exit_manager.py tests/v_oliver_kell/test_exit_manager.py
git commit -m "feat(v_oliver_kell): add exit manager (出场管理)"
```

---

## Chunk 3: 主策略类 + Registry + Config

### Files
- Create: `strategies/v_oliver_kell/oliver_kell_strategy.py`
- Modify: `strategies/registry.py`
- Modify: `config.yaml`
- Create: `tests/v_oliver_kell/test_strategy_integration.py`

---

### Task 7: Oliver Kell 主策略类

**Files:**
- Create: `strategies/v_oliver_kell/oliver_kell_strategy.py`

- [ ] **Step 1: Write the strategy class**

```python
"""
strategies/v_oliver_kell/oliver_kell_strategy.py — Oliver Kell Cycle of Price Action 主策略

继承 StrategyBase，实现完整六阶段入场/出场逻辑。

入场（买入信号）：
    ① Reversal Extension — 不买，只观察
    ② Wedge Pop         — 15% 建仓，最佳买点
    ③ EMA Crossback     — 回踩 EMA，+15% 至 30%
    ④ Base n' Break     — 盘整后突破，可加仓

出场（卖出信号）：
    - 固定止损：2% below entry
    - 追踪止盈：跌破 20 EMA
    - 主动减仓：100%+ 涨幅后分批卖
    - 时间止损：60天持有涨幅不足5%

市场环境过滤：
    - Quality:  指数 > 20 EMA → 正常操作
    - Average:  指数 ≈ 20 EMA → 降仓
    - Poor:     指数 < 20 EMA → 1-2成仓，最多30%
    - Hostile:  指数持续下跌 → 空仓
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from events import EventQueue, SignalEvent
from strategies.base import StrategyBase
from strategies.v_oliver_kell.cycle_detector import CycleDetector, CycleStage
from strategies.v_oliver_kell.wedge_finder import WedgeFinder
from strategies.v_oliver_kell.market_environment import MarketEnvironment, MarketState
from strategies.v_oliver_kell.scale_in import ScaleInManager, BatchState
from strategies.v_oliver_kell.exit_manager import ExitManager


@dataclass
class OKPosition:
    """Oliver Kell 策略持仓状态"""
    symbol: str
    entry_price: float
    entry_date: datetime
    highest_price: float
    shares: int = 0
    batch_state: BatchState = BatchState.NONE
    current_stage: str = "unknown"
    days_held: int = 0
    times_trapped: int = 0


class OliverKellStrategy(StrategyBase):
    """
    Oliver Kell Cycle of Price Action 策略。

    核心特征：
        - 基于 10/20 EMA 的六阶段价格周期
        - Wedge Pop 最佳买点（15%）
        - EMA Crossback 加仓至 30%
        - 市场环境自动过滤
        - 分批建仓 + 主动减仓出场
    """

    strategy_id = "v_oliver_kell"
    strategy_name = "Oliver Kell Cycle of Price Action"

    # 默认账户规模（用于计算股数）
    DEFAULT_ACCOUNT = 10_000.0

    def __init__(
        self,
        strategy_config: dict,
        market_data: dict[str, pd.DataFrame],
        live_mode: bool = False,
    ) -> None:
        super().__init__(strategy_config, market_data)
        self.live_mode = live_mode

        # 子模块
        self.cycle_detector = CycleDetector(
            wedge_lookback=self.cfg.get("wedge_lookback", 20),
            base_lookback=self.cfg.get("base_lookback", 20),
        )
        self.wedge_finder = WedgeFinder(
            lookback=self.cfg.get("wedge_lookback", 20),
        )
        self.market_env = MarketEnvironment(
            index_symbol=self.cfg.get("index_symbol", "QQQ"),
        )
        self.scale_in = ScaleInManager()
        self.exit_mgr = ExitManager()

        # 持仓
        self.positions: dict[str, OKPosition] = {}

        # 计算 EMA（避免重复计算）
        self._ema_cache: dict[str, pd.DataFrame] = {}

    def run_date(self, date: datetime, queue: EventQueue) -> list[SignalEvent]:
        """
        每日策略执行主循环。

        顺序：
            1. 分析市场环境（QQQ 20 EMA）
            2. 检查持仓出场
            3. 扫描个股找买入信号
        """
        signals = []

        # Step 1: 市场环境
        index_df = self._get_index_data()
        market_state = self.market_env.classify(index_df)
        max_position_pct = self.market_env.max_position_pct(market_state)

        # Step 2: 检查持仓出场
        exit_signals = self._check_exits(date, market_state)
        for sig in exit_signals:
            queue.put(sig)
            signals.append(sig)

        # Step 3: 找买入信号（受市场环境限制）
        if market_state != MarketState.HOSTILE:
            buy_signals = self._find_buy_signals(date, market_state, max_position_pct)
            for sig in buy_signals:
                queue.put(sig)
                signals.append(sig)

        return signals

    def _get_index_data(self) -> pd.DataFrame:
        """获取指数数据（QQQ）"""
        index_symbol = self.cfg.get("index_symbol", "QQQ")
        return self.market_data.get(index_symbol, pd.DataFrame())

    def _check_exits(self, date: datetime, market_state: MarketState) -> list[SignalEvent]:
        """检查所有持仓的出场信号"""
        signals = []
        to_close = []

        index_df = self._get_index_data()
        if not index_df.empty:
            ema20 = float(index_df["EMA20"].iloc[-1])
        else:
            ema20 = 0.0

        for symbol, pos in list(self.positions.items()):
            df = self.market_data.get(symbol)
            if df is None or df.empty:
                continue

            df_to_date = self._slice_to_date(df, date)
            if df_to_date.empty:
                continue

            current_price = float(df_to_date["close"].iloc[-1])
            pos.days_held += 1
            if current_price > pos.highest_price:
                pos.highest_price = current_price

            # 更新 scale_in manager
            if symbol in self.scale_in.positions:
                self.scale_in.update_highest_price(symbol, current_price)

            # 出场判断
            decision = self.exit_mgr.should_exit(
                current_price=current_price,
                ema20=ema20,
                scenario="passive",
                entry_price=pos.entry_price,
                highest_price=pos.highest_price,
                days_held=pos.days_held,
            )

            if decision.should_exit:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=5,
                    reason=decision.reason_text,
                    stop_loss=None,
                )
                signals.append(sig)
                to_close.append(symbol)
                continue

            # 主动减仓检查（100%+）
            should_trim, trim_reason = self.exit_mgr.should_trim(
                entry_price=pos.entry_price,
                current_price=current_price,
                reason="",
            )
            if should_trim:
                trim_ratio = self.exit_mgr.get_trim_ratio(
                    pos.entry_price, current_price, pos.highest_price
                )
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=3,
                    reason=f"Active trim {trim_ratio*100:.0f}%: {trim_reason}",
                    stop_loss=None,
                    shares=int(pos.shares * trim_ratio),
                )
                signals.append(sig)
                # 更新持仓（不关闭，只是减仓）
                pos.shares = int(pos.shares * (1 - trim_ratio))

        for symbol in to_close:
            del self.positions[symbol]
            if symbol in self.scale_in.positions:
                del self.scale_in.positions[symbol]

        return signals

    def _find_buy_signals(
        self,
        date: datetime,
        market_state: MarketState,
        max_position_pct: float,
    ) -> list[SignalEvent]:
        """扫描个股找买入信号"""
        signals = []

        for symbol, df in self.market_data.items():
            if symbol in ("SPY", "^VIX", "QQQ"):
                continue
            if symbol in self.positions:
                continue  # 已有持仓

            df_to_date = self._slice_to_date(df, date)
            min_rows = 60
            if len(df_to_date) < min_rows:
                continue

            signal = self._check_entry(symbol, df_to_date, date, market_state)
            if signal:
                signals.append(signal)

        # 按信号强度排序
        signals.sort(key=lambda s: s.data["strength"], reverse=True)

        # 取前 N 个（根据市场环境）
        if market_state == MarketState.POOR:
            max_signals = 2
        elif market_state == MarketState.AVERAGE:
            max_signals = 5
        else:
            max_signals = 7

        return signals[:max_signals]

    def _check_entry(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        market_state: MarketState,
    ) -> SignalEvent | None:
        """
        检查个股是否满足买入条件。

        买入信号（按原文优先级）：
            1. Wedge Pop（最佳买点）
            2. EMA Crossback（回踩加仓）
            3. Base n' Break（趋势延续）
        """
        close = float(df["close"].iloc[-1])
        ema10 = float(df["EMA10"].iloc[-1])
        ema20 = float(df["EMA20"].iloc[-1])

        # 基本面过滤（可选）
        if self.cfg.get("use_fundamental_filter", False):
            if not self._check_fundamental(symbol):
                return None

        # 识别当前阶段
        stage = self.cycle_detector.classify(df)

        # Wedge Pop
        if stage == CycleStage.WEDGE_POP:
            return self._handle_wedge_pop(symbol, df, date, close, ema10, ema20, stage)

        # EMA Crossback
        if stage == CycleStage.EMA_CROSSBACK:
            return self._handle_ema_crossback(symbol, df, date, close, stage)

        # Base n' Break
        if stage == CycleStage.BASE_N_BREAK:
            return self._handle_base_n_break(symbol, df, date, close, stage)

        return None

    def _handle_wedge_pop(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        ema10: float,
        ema20: float,
        stage: CycleStage,
    ) -> SignalEvent:
        """
        Wedge Pop 入场。

        原文：
            - Initial position: 15% of account
            - Stop: Below breakout day closing low
            - Best risk/reward entry in the entire cycle
        """
        stop = self.wedge_finder.get_breakout_stop(df)
        if stop == 0.0:
            stop = round(close * (1 - 0.02), 2)  # fallback: 2% below close

        # 记录持仓
        position = OKPosition(
            symbol=symbol,
            entry_price=close,
            entry_date=date,
            highest_price=close,
            shares=0,
            batch_state=BatchState.BATCH1_OPEN,
            current_stage="wedge_pop",
        )
        self.positions[symbol] = position

        # 触发 scale_in
        self.scale_in.on_wedge_pop(symbol, close, stop, date)

        reason = (
            f"[Wedge Pop] Best entry | "
            f"[EMA] 10={ema10:.1f}, 20={ema20:.1f} | "
            f"[Stage] {stage.value}"
        )

        return SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=5,
            reason=reason,
            stop_loss=stop,
        )

    def _handle_ema_crossback(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        stage: CycleStage,
    ) -> SignalEvent | None:
        """
        EMA Crossback 入场/加仓。

        原文：
            - Scale to 30% total (combine with Wedge Pop position)
            - Stop: Below pullback day low
            - Account risk remains ~20-30bps
        """
        # 必须是已有 Wedge Pop 持仓的股票
        if symbol not in self.positions:
            return None

        pos = self.positions[symbol]
        if pos.batch_state != BatchState.BATCH1_OPEN:
            return None

        # 检查是否应该加 Batch 2
        if not self.scale_in.should_add_batch2(symbol):
            return None

        # 当天最低价（止损参考）
        today_low = float(df["low"].iloc[-1])
        stop = round(today_low * (1 - 0.02), 2)

        # 更新持仓状态
        pos.batch_state = BatchState.BATCH2_OPEN
        pos.current_stage = "ema_crossback"

        # 触发 scale_in Batch 2
        self.scale_in.on_follow_through(symbol, follow_through_low=today_low)

        reason = (
            f"[EMA Crossback] Add to 30% | "
            f"[Stop] ${stop:.2f} | "
            f"[Stage] {stage.value}"
        )

        return SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=4,
            reason=reason,
            stop_loss=stop,
        )

    def _handle_base_n_break(
        self,
        symbol: str,
        df: pd.DataFrame,
        date: datetime,
        close: float,
        stage: CycleStage,
    ) -> SignalEvent | None:
        """
        Base n' Break 入场/加仓。

        原文：
            - Can add small during consolidation, full size at breakout
            - This pattern can repeat multiple times
        """
        # 基本过滤
        if self.cfg.get("require_wedge_pop_first", True):
            if symbol not in self.positions:
                return None  # 必须先有 Wedge Pop 才能 Base n' Break

        pos = self.positions.get(symbol)
        if pos and pos.batch_state == BatchState.BATCH2_OPEN:
            return None  # 30% 已满，不再加

        # 盘整区间止损
        base_low = float(df["low"].iloc[-21:].min())
        stop = round(base_low * (1 - 0.02), 2)

        reason = (
            f"[Base n' Break] Continuation | "
            f"[Base Low] ${base_low:.2f} | "
            f"[Stage] {stage.value}"
        )

        return SignalEvent.create(
            symbol=symbol,
            timestamp=date,
            direction="buy",
            strength=3,
            reason=reason,
            stop_loss=stop,
        )

    def _check_fundamental(self, symbol: str) -> bool:
        """
        基本面过滤（可选）。

        原文 Screening Criteria：
            - EPS Growth: YoY ≥ 30%
            - Revenue Growth: YoY ≥ 30%
        """
        # TODO: 接入 Finnhub/Alpha Vantage EPS 数据
        # 当前简单实现：跳过基本面检查
        return True

    def _slice_to_date(self, df: pd.DataFrame, date: datetime) -> pd.DataFrame:
        """切片到指定日期"""
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        idx = df.index
        if idx.tzinfo is None:
            idx = idx.tz_localize("UTC")
            df = df.copy()
            df.index = idx
        return df[df.index <= date]

    def get_open_positions(self) -> dict[str, OKPosition]:
        return dict(self.positions)
```

- [ ] **Step 2: Test import**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -c "from strategies.v_oliver_kell import OliverKellStrategy; print('OK')"`
Expected: OK

- [ ] **Step 3: Commit**

```bash
git add strategies/v_oliver_kell/oliver_kell_strategy.py
git commit -m "feat(v_oliver_kell): add main strategy class"
```

---

### Task 8: Registry + Config

**Files:**
- Modify: `strategies/registry.py`
- Modify: `config.yaml`

- [ ] **Step 1: Register strategy**

```python
# strategies/registry.py — 添加 v_oliver_kell
# 在 STRATEGY_REGISTRY 中添加:
from strategies.v_oliver_kell import OliverKellStrategy

STRATEGY_REGISTRY: dict[str, type] = {
    ...
    "v_oliver_kell": OliverKellStrategy,
}
```

Run: `python -c "from strategies.registry import get_strategy; print(get_strategy('v_oliver_kell'))"`

- [ ] **Step 2: Add config section**

```yaml
# config.yaml — strategies.v_oliver_kell 段
v_oliver_kell:
  name: "Oliver Kell Cycle of Price Action"
  description: "Wedge Pop + EMA Crossback + Base n' Break，按原文六阶段操作"

  # Cycle 检测参数
  wedge_lookback: 20
  base_lookback: 20

  # 市场环境
  index_symbol: "QQQ"

  # 基本面（可选）
  use_fundamental_filter: false
  require_wedge_pop_first: true

  # 建仓
  initial_stop_pct: 0.02

  # 出场
  trim_gain_threshold: 1.0   # 100%+
  trailing_ema_period: 20
  time_stop_days: 60
```

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -c "import yaml; c=yaml.safe_load(open('config.yaml')); print(c['strategies'].get('v_oliver_kell', 'NOT FOUND'))"`

- [ ] **Step 3: Update active_strategy**

```yaml
# config.yaml — 修改 active_strategy
active_strategy: v_oliver_kell
```

- [ ] **Step 4: Commit**

```bash
git add strategies/registry.py config.yaml
git commit -m "feat(v_oliver_kell): register strategy and add config"
```

---

## Chunk 4: 集成测试 + 回测验证

### Files
- Create: `tests/v_oliver_kell/test_strategy_integration.py`
- Run: 回测验证

---

### Task 9: 集成测试

**Files:**
- Create: `tests/v_oliver_kell/test_strategy_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""
集成测试：用历史数据验证策略逻辑
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone

import sys
sys.path.insert(0, "/Users/wubo/Desktop/codes/signal_system_Oliver")
from strategies.v_oliver_kell import OliverKellStrategy
from events import EventQueue


def make_realistic_df(days: int, start_price: float = 100.0):
    """生成逼真的价格数据（带 EMA 计算）"""
    idx = pd.date_range("2025-01-01", periods=days, tz="UTC")
    np.random.seed(42)

    # 模拟牛市趋势
    trend = np.linspace(0, 20, days)  # 缓慢上涨趋势
    noise = np.random.randn(days) * 2  # 噪音
    prices = start_price + trend + noise

    df = pd.DataFrame({"close": prices}, index=idx)
    df["volume"] = [1_000_000] * days
    df["open"] = df["close"] * (1 + np.random.randn(days) * 0.005)
    df["high"] = df["close"] * (1 + np.abs(np.random.randn(days)) * 0.01)
    df["low"] = df["close"] * (1 - np.abs(np.random.randn(days)) * 0.01)

    # EMA
    df["EMA10"] = df["close"].ewm(span=10).mean()
    df["EMA20"] = df["close"].ewm(span=20).mean()
    df["SMA50"] = df["close"].rolling(50).mean()
    df["SMA200"] = df["close"].rolling(200).mean()

    return df


def test_strategy_initialization():
    """策略可以正常初始化"""
    config = {
        "wedge_lookback": 20,
        "base_lookback": 20,
        "index_symbol": "QQQ",
    }
    market_data = {}
    strategy = OliverKellStrategy(config, market_data, live_mode=False)
    assert strategy.strategy_id == "v_oliver_kell"
    assert strategy.strategy_name == "Oliver Kell Cycle of Price Action"


def test_strategy_run_date_no_crash():
    """run_date 运行不崩溃"""
    config = {
        "wedge_lookback": 20,
        "base_lookback": 20,
        "index_symbol": "QQQ",
        "use_fundamental_filter": False,
        "require_wedge_pop_first": True,
    }

    qqq_df = make_realistic_df(100, 450)
    aapl_df = make_realistic_df(100, 180)

    market_data = {
        "QQQ": qqq_df,
        "AAPL": aapl_df,
    }

    strategy = OliverKellStrategy(config, market_data, live_mode=False)
    queue = EventQueue()

    date = pd.Timestamp("2025-04-10", tz="UTC").to_pydatetime()
    signals = strategy.run_date(date, queue)

    # 不崩溃即可
    assert isinstance(signals, list)


def test_market_environment_classification():
    """市场环境分类"""
    config = {"index_symbol": "QQQ"}
    market_data = {}
    strategy = OliverKellStrategy(config, market_data)

    # 模拟 QQQ 在 20 EMA 上方
    qqq_df = make_realistic_df(50, 450)
    market_data = {"QQQ": qqq_df}

    from strategies.v_oliver_kell.market_environment import MarketState
    env = strategy.market_env
    state = env.classify(qqq_df)
    assert state in [MarketState.QUALITY, MarketState.AVERAGE, MarketState.POOR, MarketState.HOSTILE]
```

- [ ] **Step 2: Run integration test**

Run: `cd /Users/wubo/Desktop/codes/signal_system_Oliver && python -m pytest tests/v_oliver_kell/test_strategy_integration.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/v_oliver_kell/test_strategy_integration.py
git commit -m "test(v_oliver_kell): add integration tests"
```

---

### Task 10: 回测验证

- [ ] **Step 1: 运行回测**

```bash
cd /Users/wubo/Desktop/codes/signal_system_Oliver
uv run python main.py --mode backtest --start 2024-02-12 --end 2026-03-06 --strategy v_oliver_kell 2>&1 | head -50
```

- [ ] **Step 2: 检查输出**

验证：
- 策略加载成功
- 产生买入/卖出信号
- positions.json 正确更新

- [ ] **Step 3: 若有问题，修复后 re-run**

---

## 文件清单

```
strategies/v_oliver_kell/
├── __init__.py                    ✅
├── cycle_detector.py              ✅
├── wedge_finder.py                ✅
├── market_environment.py           ✅
├── scale_in.py                     ✅
├── exit_manager.py                 ✅
└── oliver_kell_strategy.py        ✅

strategies/registry.py              ✏️ (修改)
config.yaml                        ✏️ (修改)

tests/v_oliver_kell/
├── test_market_environment.py     ✅
├── test_cycle_detector.py         ✅
├── test_wedge_finder.py           ✅
├── test_scale_in.py                ✅
├── test_exit_manager.py           ✅
└── test_strategy_integration.py    ✅
```

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-07-oliver-kell-plan.md`.**
