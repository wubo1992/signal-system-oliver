# Oliver Kell Cycle of Price Action 策略设计文档

> 逐条对照原文 [Oliver Kell System Instruction](https://www.oliverkell.com) 构建。
> 所有规则直接引用或节录自原文，无自行发明。

---

## 1. 策略概述

| 项目 | 内容 |
|------|------|
| 策略 ID | `v_oliver_kell` |
| 策略名称 | Oliver Kell Cycle of Price Action |
| 核心框架 | Cycle of Price Action（六阶段模型）|
| 替换策略 | `v_eps_v2` |
| 目标用户 | 希望原汁原味实现 Oliver Kell 方法论 |

---

## 2. Cycle of Price Action — 六阶段模型

### 2.1 完整周期（原文）

```
[Complete Uptrend Cycle]
Reversal Extension → Wedge Pop → EMA Crossback → Base n' Break → Exhaustion Extension (Top)

[Complete Downtrend Cycle]
Wedge Drop → EMA Throwback → Downside Break → Retest
```

### 2.2 各阶段详细规则

#### ① Reversal Extension — Bottom Panic Signal

**原文规则：**
> **Rule**: Do NOT buy here. Wait for confirmation signals. Watch for strong support absorption.

**实现：**
- 不发出买入信号
- 标记为"观察阶段"
- 等待 Wedge Pop 确认

---

#### ② Wedge Pop — "Money Pattern"（最佳买点）

**原文 Identification：**
- Price bounces from low, consolidates in contracting Wedge
- Price breaks Wedge upper bound AND crosses above 10/20 EMA
- Volume expansion (accumulation confirmation)
- Relative Strength (RS Line) starts leading the market

**原文 Entry Rules：**
- Enter at Wedge Pivot Point breakout
- Initial position: **15%** of account
- Stop: Below breakout day **closing low**
- This is the **best risk/reward** entry in the entire cycle

**实现细节：**
- 建仓：15% 仓位
- 止损：突破日**收盘价最低点**以下 1-2%
- Wedge 识别：过去 N 日价格呈收缩楔形，高点连线和低点连线收敛

**Strong Signal Boosters（原文）：**
- Wedge Pop 同时"收复"前期 Wedge Drop 高点（Knockout Bar rally）
- Ignition Bar：单日巨量暴涨确认趋势改变

---

#### ③ EMA Crossback — Low-Risk Second Entry

**原文 Identification：**
- After Wedge Pop, price gently pulls back to 10/20 EMA
- Pullback is **slow, low volume** (not sharp drop)
- EMAs are now upward-sloping (support strengthening)
- Supportive accumulation behavior appears at EMA touch

**原文 Entry Rules：**
- Enter when price finds support at EMA and turns up
- Can be: (A) Initial entry OR (B) Add-on after Wedge Pop
- Scale to **30% total** (combine with Wedge Pop position)
- Stop: Below pullback day **low**
- Account risk remains ~20-30bps

**实现细节：**
- 作为 Wedge Pop 后的加仓点（非新信号）
- 目标仓位：累计 30%
- 止损：回踩日最低价以下 1-2%
- 要求：回踩速度慢、量能低（不是急速下跌）

---

#### ④ Base n' Break — Trend Continuation

**原文 Identification：**
- Price consolidates for weeks (typically **2-4 weeks**), volume dries up ("volume exhaustion")
- EMAs compress toward price during consolidation
- Price holds **Higher Lows** above EMAs
- Breaks upper consolidation bound with volume expansion

**原文 Rules：**
- Can add small during consolidation, full size at breakout
- Continuously raise trailing stop
- This pattern can **repeat multiple times** within one major trend

**Variant Patterns（原文）：**
- Bull Flag, Bull Pennant, Cup with Handle, Flat Base, VCP, Double Bottom, Descending Wedge, Wick Play

**实现细节：**
- 盘整期：2-4 周
- 盘整期间可小幅加仓，突破时加满
- 止损：盘整区间最低价
- 每次 Base n' Break 都可加仓或新开

---

#### ⑤ Exhaustion Extension — Top Warning

**原文 Identification：**
- Price far from 10/20 EMA (typically **30-50%+**)
- Volume shows climax run
- K-line shows large alternating candles, "flagpole" rise
- Distance to EMA exceeds historical normal range

**原文 Rules：**
- **Actively trim** (not full exit), lock partial profits
- If up **100%+ from cost basis**, heavily reduce
- Before earnings: actively trim to control binary risk
- **Do NOT open new positions here**

**实现：**
- 不开新仓
- 已有仓位：涨幅超 100% 开始主动减仓
- 出现顶部信号（远离 EMA、巨量、阴阳烛交替）开始 trim

---

#### ⑥ Wedge Drop — Downtrend Confirmation

**原文 Rules：**
- Reduce or exit immediately
- No bottom-fishing below EMA
- Wait for complete bottom repair (new Reversal Extension) before reconsidering

**实现：**
- 触发卖出信号
- 不抄底
- 等新的 Reversal Extension 确认后再看

---

## 3. 移动平均线系统

### 3.1 参数（原文 Table）

| MA | Type | Purpose |
|----|------|---------|
| **10-day** | EMA | Core short-term trend reference, stop trailing baseline |
| **20-day** | EMA | Core mid-term trend reference, pullback buy zone |
| **50-day** | SMA | Mid-term trend filter, CAN SLIM trend qualification |
| **200-day** | SMA | Long-term trend, bull/bear dividing line |

### 3.2 MA 层级判断（原文）

```
[Bullish Bias Confirmed]
Price > 10 EMA > 20 EMA > 50 SMA > 200 SMA
→ Perfect Stack = strongest trend phase

[Bearish Bias Confirmed]
Price < 10 EMA < 20 EMA < 50 SMA < 200 SMA
→ Reverse Stack = extremely high risk for longs

[Rules]
- 10/20 EMA rising + price above = bullish, seek entries
- 10/20 EMA falling + price below = bearish, stay defensive
- Price supported above EMAs = can be aggressive
- Price rejected below EMAs = stay defensive
```

---

## 4. 市场环境分类

### 4.1 四档分类（原文 Table）

| Market State | Criteria | Operation Mode |
|--------------|----------|----------------|
| **Quality** | Index above 20 EMA, multiple leaders following | 6-7 core positions, margin OK (~190% exposure) |
| **Average** | Index oscillating near 20 EMA | 3-5 positions, cash-heavy |
| **Poor** | Index below 20 EMA, unable to profit | 1-2 positions, max 30% total exposure |
| **Hostile** | Systematic decline | All cash, wait and observe |

### 4.2 实现方式

- 用 QQQ（或 SPY）的 20 EMA 判断市场状态
- Poor 时：允许 1-2 成仓，最多 30%
- Hostile 时：不出买入信号
- Quality/Average 时：正常按信号操作

---

## 5. 分批建仓（Scale-In Method）

### 原文（Section 6.2）

```
Batch 1 (15% position):
→ Entry: Price supported at 20 EMA / Wedge Pop pivot
→ Stop: 1-2% below entry
→ Account risk: ~15-30bps (minimal risk)

Batch 2 (+15% = 30% total):
→ Condition: Batch 1 profitable, follow-through confirmation next day
→ Simultaneously raise stop to "follow-through day" low
→ Total account risk still ~20-30bps

Subsequent Adds:
→ Stock continues strong performance
→ Raise trailing stop with each add
→ Can reach margin status (in quality environments)
```

### 实现细节

| 批次 | 仓位 | 触发条件 | 止损 |
|------|------|---------|------|
| Batch 1 | 15% | Wedge Pop 突破 | 突破日收盘价最低 - 1-2% |
| Batch 2 | +15% = 30% | Batch 1 盈利 + 次日确认 | 确认日最低价 |
| 后续加仓 | - | 强势持续，每次 raise trailing stop | - |

---

## 6. 止损规则

### 原文 Table（Section 6.3）

| Scenario | Stop Placement |
|----------|---------------|
| Wedge Pop | Below breakout day **closing low** |
| EMA Crossback | Below pullback day **low** |
| Base n' Break | Below base range **low** |
| Position Trailing | 10 EMA (when short-term trend strong) or 20 EMA (primary trailing stop) |
| Multi-week trend | Let "the most important MA" dictate stop level |

### 实现

- **初始止损**：1-2% below entry（原文 ~15-30bps account risk）
- **追踪止损**：10 EMA（强势时）或 20 EMA（主追踪）
- **分场景**：Wedge Pop / EMA Crossback / Base n' Break 各有不同止损逻辑

---

## 7. 出场规则

### 原文 Active Trim Signals（Section 6.4）

```
[Active Trim Signals]
- Up 100%+ from base → heavy trim
- Exhaustion Extension characteristics appear → start trimming
- Before earnings → active trim to control binary risk
- "Trim into strength, don't sell into weakness"
```

### 原文 Passive Stop Signals（Section 6.4）

```
[Passive Stop Signals]
- Price decisively breaks below 20 EMA → full exit
- Failed breakout (breaks out then immediately reverses, no follow-through) → stop without hesitation
- Same stock traps you 3 times with no progress → wrong timing, exit
```

### 实现

**主动出场（分批止盈）：**
- 涨幅超 100% → 开始 heavy trim
- 出现 Exhaustion Extension 特征 → 开始 trim
- 财报前 → 主动减仓控风险
- 原则：Trim into strength, don't sell into weakness

**被动止损：**
- 价格有效跌破 20 EMA → 全出
- 假突破（突破后立即反转）→ 无犹豫止损
- 同一只股票被套 3 次 → 退出

---

## 8. 指数优先分析

### 原文（Section 7.1）

> ALWAYS analyze major index (QQQ/SPY) Cycle of Price Action position BEFORE analyzing individual stocks

```
Index position in cycle → determines overall position bias
Index Wedge Pop → stocks likely forming major bottoms, actively seek leaders
Index EMA Crossback → individual stock entries, stage adds
Index Base n' Break → strongest phase, full deployment
Index Exhaustion Extension → start defense, lock profits
Index Wedge Drop → exit/light positions, wait for new cycle
```

### 实现

- 每日先分析 QQQ/SPY 的 Cycle of Price Action 阶段
- 指数阶段决定整体仓位偏向
- 个股信号需与指数阶段匹配

---

## 9. 股票筛选基础条件

### 原文（Section 5.1）

| Dimension | Standard |
|-----------|----------|
| **Price** | ≥ $20 |
| **Avg Daily Volume** | ≥ 500,000 shares |
| **Market Cap** | $2B – $25B |
| **EPS Growth** | YoY ≥ 30%, ideally triple-digit |
| **Revenue Growth** | YoY ≥ 30%, accelerating preferred |
| **Industry Position** | Sector leader, industry in uptrend |

### 实现

- 基本面筛选：EPS YoY ≥ 30%，营收 YoY ≥ 30%
- 技术筛选：价格 ≥ $20，成交量 ≥ 500K
- 市值：$2B - $25B（可选，暂无 API 实时获取）

---

## 10. 文件结构

```
strategies/
├── v_oliver_kell/
│   ├── __init__.py
│   ├── oliver_kell_strategy.py    ← 主策略类
│   ├── cycle_detector.py           ← Cycle of Price Action 六阶段识别
│   ├── wedge_finder.py             ← Wedge 形态识别
│   ├── market_environment.py       ← 市场环境判断（QQQ 20 EMA）
│   ├── scale_in.py                 ← 分批建仓逻辑
│   └── exit_manager.py             ← 出场管理（主动+被动）
```

---

## 11. 与现有系统的关系

| 组件 | 复用 | 说明 |
|------|------|------|
| StrategyBase | ✅ 继承 | 作为基类 |
| EventQueue / SignalEvent | ✅ 复用 | 与现有框架一致 |
| positions.json | ✅ 扩展 | 增加批次状态字段 |
| config.yaml | ✅ 新增段 | `strategies.v_oliver_kell` |
| registry.py | ✅ 注册 | 新增 `v_oliver_kell` 条目 |
| data/fetcher.py | ✅ 复用 | 数据获取不变 |
| 指数数据 | ✅ 复用 | QQQ/SPY 数据走同一套 fetcher |

---

## 12. positions.json 扩展字段

```json
{
  "symbol": "AAPL",
  "batch_1_entry_price": 150.00,
  "batch_1_entry_date": "2026-05-01",
  "batch_1_shares": 10,
  "batch_2_entry_price": 152.00,
  "batch_2_entry_date": "2026-05-02",
  "batch_2_shares": 10,
  "total_shares": 20,
  "avg_cost": 151.00,
  "highest_price": 165.00,
  "current_stage": "Base_n_Break",
  "market_environment": "Quality",
  "highest_batch_2_follow_through_low": 151.50,
  "times_trapped": 0
}
```

---

## 13. 待明确事项

1. **EPS/营收数据来源**：当前系统使用 Finnhub/Alpha Vantage，是否满足 Oliver Kell 的基本面筛选需求？
2. **市值筛选**：暂无实时市值 API，是否暂时跳过 $2B-$25B 限制？
3. **RS Line（相对强度线）**：原文提到但实现复杂，是否首期跳过？

---

## 14. 实现优先级

**Phase 1（核心）：**
- [ ] Oliver Kell 策略类骨架
- [ ] Cycle of Price Action 六阶段识别
- [ ] Wedge Pop 信号 + 15% 建仓
- [ ] EMA Crossback 加仓至 30%
- [ ] 市场环境过滤
- [ ] 止损逻辑（1-2% below entry）

**Phase 2（完整）：**
- [ ] Base n' Break 信号
- [ ] 分批止盈（100%+ trim）
- [ ] 追踪止损（10/20 EMA trailing）
- [ ] positions.json 批次持久化

**Phase 3（可选）：**
- [ ] Exhaustion Extension 识别
- [ ] RS Line 计算
- [ ] 基本面筛选（EPS/营收）
