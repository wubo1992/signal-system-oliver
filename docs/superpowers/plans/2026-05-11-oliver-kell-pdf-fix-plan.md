# Oliver Kell 策略 PDF 还原修复计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复当前实现与 PDF 原文的关键偏差，使策略如实反映 Oliver Kell 理论精髓，显著提升回测绩效（目标：胜率>40%，夏普>1.0）。

**Architecture:**
- 修改 3 个文件：`oliver_kell_strategy.py`（出场+止损锚点）、`cycle_detector.py`（入场前提）、`scale_in.py`（已修复批次比例）
- OKPosition 新增 `entry_stop_price` 字段记录入场时的关键支撑低点，作为绝对止损锚点
- `cycle_detector.classify()` 中 `EMA_CROSSBACK` 触发条件由 `pullback_count <= 2` 改为 `pullback_count == 1`（严格要求第1次回踩）

**已完成的修复（不在计划内）：**
- ✅ Batch1_PCT: 30% → 20%
- ✅ Extension 卖出：第1次20%、第2次50%、第3次全卖
- ✅ 入场价门槛：$20 → $10
- ✅ 成交量门槛：50万 → 100万
- ✅ `is_perfect_stack` 移除 SMA200 要求，只保留 EMA 多头排列
- ✅ `_is_ema_crossback` 已限制 `pullback_count <= 2`

**Tech Stack:** Python 3.13, pandas, numpy

---

## Chunk 1: 止损锚点修复（核心）

### Files
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py`
- Modify: `strategies/v_oliver_kell/cycle_detector.py`（get_wedge_info 返回 breakout_day_low）

---

### Task 1: OKPosition 添加 `entry_stop_price` 字段

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py:40-65`

- [ ] **Step 1: 在 OKPosition dataclass 添加 `entry_stop_price` 字段**

```python
# 在 OKPosition dataclass 的 trailing_stop_price 字段后添加：
# 入场时的关键支撑低点（PDF: breakout day low / pullback day low / base range low）
# 这是绝对止损锚点，不是 entry_price 的百分比
entry_stop_price: float = 0.0
```

---

### Task 2: Wedge Pop 入场记录正确的 `entry_stop_price`

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — `_handle_wedge_pop` 方法

- [ ] **Step 1: 找到 `wedge_info = self.cycle_detector.get_wedge_info(df)` 之后**

在创建 `OKPosition` 之前，添加：

```python
# PDF Page 17: "Stop: Below breakout day closing low"
# 关键支撑 = wedge 突破日的最低点（不是 entry_price 的百分比）
wedge_info = self.cycle_detector.get_wedge_info(df)
if wedge_info is not None:
    # wedge_info 应包含 breakout_day_low（突破日的最低价）
    # 如果 wedge_finder 还没返回这个字段，先用 99% 的 close 作为 fallback
    breakout_low = wedge_info.get("breakout_day_low", close * 0.99)
else:
    yesterday_low = float(df["low"].iloc[-2])
    breakout_low = yesterday_low  # Fallback: 用昨天最低价

stop = round(breakout_low * 0.99, 2)  # 1% buffer
```

- [ ] **Step 2: 在 OKPosition 创建时添加 `entry_stop_price=breakout_low`**

在 `_handle_wedge_pop` 的 `OKPosition(...)` 中添加：
```python
entry_stop_price=breakout_low,
```

---

### Task 3: Wedge Pop — `wedge_finder.get_wedge_info()` 返回 `breakout_day_low`

**Files:**
- Modify: `strategies/v_oliver_kell/wedge_finder.py`

- [ ] **Step 1: 找到 `WedgeResult` dataclass，添加 `breakout_day_low` 字段**

```python
@dataclass
class WedgeResult:
    wedge_type: WedgeType
    upper_bound: float
    lower_bound: float
    breakout_detected: bool
    breakout_direction: str
    breakout_day_low: float = 0.0  # ← 添加：突破日的最低价
```

- [ ] **Step 2: 在 `find_wedge()` 返回前，正确计算并填充 `breakout_day_low`**

当前代码的 `find_wedge()` 返回时，`breakout_day_low` 已是 `today_low`（收盘价的当日最低）。但需要确保它真的是**突破日**的最低价——如果今天没有突破，那这个字段应该是 0.0。

找到返回语句并确保：
```python
# 如果今天没有向上突破，breakout_day_low = 0.0
return WedgeResult(
    ...
    breakout_day_low=today_low if breakout_detected and breakout_direction == "up" else 0.0,
)
```

---

### Task 4: EMA Crossback 入场记录 `entry_stop_price = yesterday_low`

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — `_handle_ema_crossback`

- [ ] **Step 1: 在 `_handle_ema_crossback` 的 OKPosition 创建时添加**

在 `yesterday_low = float(df["low"].iloc[-2])` 之后，OKPosition 添加：
```python
entry_stop_price=yesterday_low,  # PDF Page 20: pullback day low
```

---

### Task 5: Base n' Break 入场记录 `entry_stop_price = base_low`

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — `_handle_base_n_break`

- [ ] **Step 1: 在 `_handle_base_n_break` 的 OKPosition 创建时添加**

在 `base_low = float(df["low"].iloc[-lookback:].min())` 之后，OKPosition 添加：
```python
entry_stop_price=base_low,  # PDF Page 20: base range low
```

---

### Task 6: Hard Stop 改为使用 `entry_stop_price`（移除百分比锚点）

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — 找到 `if current_price < pos.entry_price * 0.92` 逻辑

- [ ] **Step 1: 替换为 entry_stop_price 判断**

```python
# OLD:
if current_price < pos.entry_price * 0.92:
    reason = f"[Hard Stop 8%] ..."

# NEW (PDF Page 17, 20, 47):
# 跌破入场时记录的关键支撑低点 → 全卖
# 保留 8% 百分比作为极端情况下的最后保险（当 entry_stop_price 为 0 时）
if pos.entry_stop_price > 0 and current_price < pos.entry_stop_price:
    sig = SignalEvent.create(
        symbol=symbol,
        timestamp=date,
        direction="sell",
        strength=5,
        reason=f"[Stop Hit] ${current_price:.2f} < key support ${pos.entry_stop_price:.2f}",
        stop_loss=None,
        cycle_stage="stop_hit",
        current_price=current_price,
    )
    signals.append(sig)
    to_close.append(symbol)
    continue
elif pos.entry_stop_price == 0 and current_price < pos.entry_price * 0.92:
    # Fallback: 极端情况（无有效支撑数据）
    sig = SignalEvent.create(
        symbol=symbol,
        timestamp=date,
        direction="sell",
        strength=5,
        reason=f"[Hard Stop 8%] ${current_price:.2f} < ${pos.entry_price * 0.92:.2f}",
        stop_loss=None,
        cycle_stage="hard_stop",
        current_price=current_price,
    )
    signals.append(sig)
    to_close.append(symbol)
    continue
```

---

### Task 7: Ignite Bar Low — 主动上调止损锚点（不只是被动追踪）

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — 在 `_detect_and_update_ignite_bar` 调用之后

- [ ] **Step 1: 找到 `_detect_and_update_ignite_bar` 调用位置（约 line 230）**

在该调用**之后**，添加：

```python
# === 主动上调止损锚点到 Ignite Bar low（PDF Page 48-49）===
# "when we see an ignition bar low, we want to adjust our stops to the low of that bar"
# Ignite Bar 低点只上调不下调（一旦提高就不再降低）
if pos.ignite_bar_low > pos.entry_stop_price:
    old_stop = pos.entry_stop_price
    pos.entry_stop_price = pos.ignite_bar_low
    # 不需要发信号，只是内部更新止损锚点
```

---

## Chunk 2: EMA 追踪止损修复

### Files
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py`

---

### Task 8: 跌破 EMA10 → 逐步减仓而非立即全卖

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py`

- [ ] **Step 1: 找到 `if current_price < ema10:` 的逻辑（应该已不存在了）**

如果还存在，用下面逻辑替换。如果已删除，跳过此步。

- [ ] **Step 2: 如果存在则替换为：**

```python
# === 收盘价确认跌破 EMA10 → 逐步减仓（PDF Page 11, 48）===
# PDF 的意思是"收盘在 EMA10 下方说明趋势可能结束"，
# 不是一跌破就全卖。正确做法：
#   - 连续第1天跌破 EMA10 → 趋势警告，减仓50%，止损提高到 EMA10
#   - 连续第2天跌破 EMA10 → 确认走弱，卖出剩余50%
if current_price < ema10:
    # 检查昨天是否也在 EMA10 下方（确认趋势）
    if len(df_to_date) >= 2:
        prev_close = float(df_to_date["close"].iloc[-2])
        prev_ema10 = float(df_to_date["close"].ewm(span=10).mean().iloc[-2])
        was_below_ema10_yesterday = prev_close < prev_ema10

        if was_below_ema10_yesterday:
            # 连续第2天跌破 → 确认，卖出剩余
            sig = SignalEvent.create(
                symbol=symbol,
                timestamp=date,
                direction="sell",
                strength=5,
                reason=f"[EMA10 Break Confirmed] 2nd day below EMA10 ${ema10:.2f} - exit all",
                stop_loss=None,
                cycle_stage="ema10_break_confirmed",
                current_price=current_price,
            )
            signals.append(sig)
            to_close.append(symbol)
            continue
        else:
            # 第1天跌破 → 警告，减仓50%，止损提高到 EMA10
            trim_ratio = 0.50
            shares_to_sell = int(pos.shares * trim_ratio) if pos.shares > 0 else 0
            if shares_to_sell > 0:
                sig = SignalEvent.create(
                    symbol=symbol,
                    timestamp=date,
                    direction="sell",
                    strength=3,
                    reason=f"[EMA10 Warning] Close ${current_price:.2f} < EMA10 ${ema10:.2f} - trim 50%",
                    stop_loss=None,
                    shares=shares_to_sell,
                    cycle_stage="ema10_warning",
                    current_price=current_price,
                )
                signals.append(sig)
                pos.shares -= shares_to_sell
                # 主动把止损锚点提高到 EMA10（追踪）
                pos.entry_stop_price = max(pos.entry_stop_price, ema10)
                if pos.shares <= 0:
                    to_close.append(symbol)
                    continue
```

---

### Task 9: 保留 EMA20 Break 作为终极止损

- [ ] **Step 1: 确认 EMA20 Break 逻辑存在且不变**

EMA20 Break（全卖）逻辑保留，这是最终防线，不改。

---

## Chunk 3: 入场前提条件强化

### Files
- Modify: `strategies/v_oliver_kell/cycle_detector.py`
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py`

---

### Task 10: EMA Crossback 改为严格要求第1次回踩（`pullback_count == 1`）

**Files:**
- Modify: `strategies/v_oliver_kell/cycle_detector.py` — `classify()` 方法

- [ ] **Step 1: 找到 `pullback_count <= 2` 并改为 `pullback_count == 1`**

```python
# OLD:
if pullback_count <= 2:
    if self._is_ema_crossback(df, ...):
        return CycleStage.EMA_CROSSBACK

# NEW: PDF Page 11, 20 — "first pullback to the 10/20 EMA"
# pullback_count == 1 表示这是 Wedge Pop 之后的第1次回踩
# pullback_count == 0 表示刚发生 Wedge Pop 还没回踩过（还不是 EMA Crossback）
if pullback_count == 1:
    if self._is_ema_crossback(df, ...):
        return CycleStage.EMA_CROSSBACK
```

---

### Task 11: EMA Crossback 入场 — 成交量确认

**Files:**
- Modify: `strategies/v_oliver_kell/cycle_detector.py` — `_is_ema_crossback`

- [ ] **Step 1: 在 `_is_ema_crossback` 的 Day 2 检查之后（收盘 > 开盘 确认之后），添加成交量验证**

找到 Day 2 反弹确认的检查，在其后添加：

```python
# Day 2 收盘在波幅上半部
if today_close < today_open:
    return False

# === 添加：Day 2 成交量 > Day 1（放量确认，PDF Page 11）===
today_vol = float(df["volume"].iloc[-1])
yesterday_vol = float(df["volume"].iloc[-2])
if today_vol <= yesterday_vol:
    return False  # 没有放量，不确认
```

---

### Task 12: Variant Patterns — 从 UNKNOWN 降级改为平行入场信号

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — `_check_entry`

- [ ] **Step 1: 找到 `if stage == CycleStage.UNKNOWN:` 条件**

将 Variant Patterns 的检查从 `if stage == CycleStage.UNKNOWN:` 内部移出，作为与 `stage` 判断**平行的独立检查**：

```python
# OLD — 只在 UNKNOWN 时检查 Variant Patterns:
# if stage == CycleStage.UNKNOWN:
#     if market_state not in (...):
#         if self.cycle_detector.is_vcp(df): ...
#         if self.cycle_detector.is_bull_flag(df): ...

# NEW — Variant Patterns 是平行入场信号，不依赖 UNKNOWN：
# 无论 stage 是什么（除了 EXHAUSTION_EXTENSION），只要满足 Variant Pattern 条件就考虑买入
# 但只在 POOR/HOSTILE 市场状态不触发（与其他入场一致）
if stage != CycleStage.EXHAUSTION_EXTENSION and stage != CycleStage.WEDGE_DROP:
    if market_state not in (MarketState.POOR, MarketState.HOSTILE):
        # Variant Patterns 优先级最低，只有非 POOR/HOSTILE 市场才操作
        # 注意：仍然需要在其他入场信号之后处理（因为有 deduplication）
```

实际上更简单的做法是保持 UNKNOWN 条件不变，但提高 Variant Patterns 的优先级——把它移到 `_check_entry` 中 `stage == CycleStage.UNKNOWN` 之前，并在 `market_state` 检查之后：

```python
# 在 _check_entry 方法中，找到 return None 之前的 Variant Patterns 逻辑
# 把 if stage == CycleStage.UNKNOWN: 改为直接检查（不再限制 UNKNOWN）
# 但保留 market_state 和其他过滤

# === Variant Patterns（与 stage 无关，平行入场信号）===
if market_state not in (MarketState.POOR, MarketState.HOSTILE):
    pattern_signal = self._check_variant_pattern_for_entry(symbol, df, date, close)
    if pattern_signal:
        return pattern_signal
```

为此，需要在 `_check_entry` 中添加一个新方法 `_check_variant_pattern_for_entry`，把现有 `is_vcp/is_bull_flag/is_bull_pennant` 的检查和 `_handle_variant_pattern` 封装进去。

**简化方案（不新增方法）：**

在 `_check_entry` 中找到当前这段代码：
```python
if stage == CycleStage.UNKNOWN:
    if market_state not in (MarketState.POOR, MarketState.HOSTILE):
        if self.cycle_detector.is_vcp(df):
            return self._handle_variant_pattern(...)
```

替换为：
```python
# === Variant Patterns：平行入场信号，不依赖 UNKNOWN ===
# PDF 展示的 Bull Flag / Bull Pennant / VCP 是独立入场形态
if stage not in (CycleStage.EXHAUSTION_EXTENSION, CycleStage.WEDGE_DROP, CycleStage.REVERSAL_EXTENSION):
    if market_state not in (MarketState.POOR, MarketState.HOSTILE):
        # 检查是否有 Variant Pattern
        pattern_name = None
        if self.cycle_detector.is_vcp(df):
            pattern_name = "VCP"
        elif self.cycle_detector.is_bull_flag(df):
            pattern_name = "Bull Flag"
        elif self.cycle_detector.is_bull_pennant(df):
            pattern_name = "Bull Pennant"

        if pattern_name and symbol not in self.positions:
            return self._handle_variant_pattern(symbol, df, date, close, pattern_name)
```

---

## Chunk 4: Base n' Break 出场阶段 + 时间止损修复

### Files
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py`

---

### Task 13: Base n' Break 阶段 — 更积极的止盈

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py` — `_check_exits`

- [ ] **Step 1: 在 Extension 卖出逻辑中，当 `current_stage == "base_n_break"` 时更激进**

在 Extension 卖出逻辑（`if pos.extension_count > 0 and pos.highest_extension_price > 0:`）开头添加：

```python
# === Base n' Break 阶段：第1次 Extension 就应该卖 50%（PDF Page 10, 20）===
# "Second extension from the 10 EMA is generally a good place to take profits"
# Base n' Break 意味着这是第2+次 Extension，比普通 Wedge Pop/EMA Crossback 入场的持仓
# 需要更早、更积极地止盈
is_base_n_break_position = (pos.current_stage == "base_n_break")

if pos.extension_count > 0 and pos.highest_extension_price > 0:
    ref_price = max(pos.highest_extension_price, pos.last_sell_reference_price)
    if ref_price > 0 and current_price < ref_price * 0.95:
        if is_base_n_break_position:
            # Base n' Break 持仓：第1次 Extension 就卖 50%
            trim_ratio = 0.50
        elif pos.extension_count == 1:
            trim_ratio = 0.20
        elif pos.extension_count == 2:
            trim_ratio = 0.50
        else:
            trim_ratio = 1.00  # 第3次全卖
        # ... 后续卖出逻辑不变 ...
```

---

### Task 14: 时间止损 — 移除 30 天规则，改为 90 天宽容阈值

**Files:**
- Modify: `strategies/v_oliver_kell/oliver_kell_strategy.py`

- [ ] **Step 1: 找到 `if pos.days_held > 30 and gain_pct < 5.0:` 并替换**

```python
# OLD (Minervini 逻辑):
# if pos.days_held > 30 and gain_pct < 5.0:

# NEW: Oliver Kell 用 EMA 趋势判断，不设固定时间止损
# 保留一个极宽容的 90 天兜底（涨幅 < 10% 才触发）
if pos.days_held > 90 and gain_pct < 10.0:
    sig = SignalEvent.create(
        symbol=symbol,
        timestamp=date,
        direction="sell",
        strength=2,  # 低优先级，不是主要出场信号
        reason=f"[Long-term Time Stop] Held {pos.days_held} days, gain {gain_pct:.1f}% < 10%",
        stop_loss=None,
        cycle_stage="time_stop",
        current_price=current_price,
    )
    signals.append(sig)
    to_close.append(symbol)
    continue
```

---

## Chunk 5: 验证与回测

### Files
- Run: `backtest/engine.py`

---

### Task 15: Python 语法验证

- [ ] **Step 1: 验证所有修改文件的语法**

```bash
.venv/bin/python -c "
import ast
files = [
    'strategies/v_oliver_kell/scale_in.py',
    'strategies/v_oliver_kell/cycle_detector.py',
    'strategies/v_oliver_kell/oliver_kell_strategy.py',
    'strategies/v_oliver_kell/wedge_finder.py',
]
for f in files:
    with open(f) as fh:
        src = fh.read()
    try:
        ast.parse(src)
        print(f'✓ {f}')
    except SyntaxError as e:
        print(f'✗ {f}: {e}')
"
```

预期：4 个文件全部 ✓

---

### Task 16: 全量回测（2026-01-01 ~ 2026-05-11）

- [ ] **Step 1: 运行回测**

```bash
.venv/bin/python main.py --mode backtest --start 2026-01-01 --end 2026-05-11 --strategy v_oliver_kell
```

**预期改善指标：**
- 止损锚点精准化 → 最大回撤可能略增（因为更严格按支撑止损），但更符合 PDF
- EMA 追踪逐步减仓 → 减少被反转止损 → 胜率提升
- 入场前提严格化（pullback_count==1, volume confirm）→ 信号数减少但质量提升
- Variant Patterns 平行化 → 信号增加但覆盖更多形态
- Base n' Break 止盈更早 → 锁住更多利润

**目标：** 胜率 > 40%，夏普 > 1.0（当前各 30.9% 和 0.16）

---

## 改动汇总

| Task | 改动 | PDF 原文依据 | 文件 |
|------|------|------------|------|
| 1 | OKPosition 加 `entry_stop_price` | Page 17, 20 | `oliver_kell_strategy.py` |
| 2-3 | Wedge Pop 止损 = breakout_day_low | Page 17 | `oliver_kell_strategy.py` + `wedge_finder.py` |
| 4 | EMA Crossback 止损 = yesterday_low | Page 20 | `oliver_kell_strategy.py` |
| 5 | Base n' Break 止损 = base_low | Page 20 | `oliver_kell_strategy.py` |
| 6 | Hard Stop 改为 `entry_stop_price` 锚点 | Page 17, 20, 47 | `oliver_kell_strategy.py` |
| 7 | Ignite Bar low 主动上调止损锚点 | Page 48-49 | `oliver_kell_strategy.py` |
| 8 | EMA10 跌破 → 第1天减50%，第2天全卖 | Page 11, 48 | `oliver_kell_strategy.py` |
| 10 | `pullback_count == 1`（严格第1次回踩） | Page 11, 20 | `cycle_detector.py` |
| 11 | EMA Crossback 加 Day2 放量确认 | Page 11 | `cycle_detector.py` |
| 12 | Variant Patterns 改为平行入场信号 | Page 38-43 | `oliver_kell_strategy.py` |
| 13 | Base n' Break 持仓第1次 Extension 卖 50% | Page 10, 20 | `oliver_kell_strategy.py` |
| 14 | 时间止损 30天 → 90天，涨幅阈值 5% → 10% | Oliver Kell 趋势逻辑 | `oliver_kell_strategy.py` |
