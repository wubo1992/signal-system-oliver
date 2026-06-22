# Oliver Kell Cycle of Price Action 信号系统 — 产品PRD

> **文档版本**: 2026-05-15
> **当前策略**: v_oliver_kell
> **状态**: 线上运行中

---

## 一、产品概述

### 1.1 核心功能

Oliver Kell Cycle of Price Action 信号系统是一个基于市场价格循环理论的事件驱动交易系统。系统每日自动扫描股票池，产生以下类型的交易信号：

| 信号方向 | 信号类型 | 说明 |
|---------|---------|------|
| **买入** | Wedge Pop | 最佳买点，楔形突破 |
| **买入** | EMA Crossback | 回踩EMA支撑入场 |
| **买入** | Base n' Break | 盘整后趋势延续 |
| **买入** | Variant Patterns | VCP / Bull Flag / Bull Pennant |
| **卖出** | Exit Signals | 止损/止盈/时间止损 |
| **做空** | Wedge Drop Short | 楔形跌破做空 |
| **做空** | Exhaustion Short | 顶部衰竭做空 |

### 1.2 技术架构

```
股票池(UNIVERSE.md)
    ↓
数据层(data/fetcher.py)
    ├── Alpaca Market Data API (主源，IEX feed)
    ├── Yahoo Finance API (备用)
    ├── VIX GitHub (指数波动率)
    └── 本地缓存(data/cache/*.pkl)
    ↓
策略层(strategies/v_oliver_kell/)
    ├── cycle_detector.py   — 6阶段识别
    ├── wedge_finder.py     — 楔形检测
    ├── market_environment.py — 市场环境分类
    ├── exit_manager.py     — 出场管理
    └── scale_in.py         — 分批建仓
    ↓
信号层(signals/)
    ├── generator.py        — 信号输出(CSV+控制台)
    ├── oliver_kell_radar_report.py — 雷达报告
    ├── report.py          — 日报
    └── positions.py        — 持仓追踪
    ↓
回测层(backtest/engine.py)
```

---

## 二、信号类型详解

### 2.1 买入信号

#### 2.1.1 Wedge Pop（楔形突破）⭐⭐⭐⭐⭐

**定义**：价格从楔形整理中向上突破。

**入场条件**：
1. EMA10 和 EMA20 向上
2. 价格突破楔形上轨
3. RS Line 领先（高于 QQQ）
4. 周线趋势向上

**止损**：突破日收盘价 × 0.98（2%固定止损）

**持仓**：30%仓位

---

#### 2.1.2 EMA Crossback（回踩入场）⭐⭐⭐⭐

**定义**：价格回踩EMA后向上确认的入场信号（两日模式）。

**入场条件（逐项检查）**：

| 步骤 | 条件 | 要求 |
|------|------|------|
| Day 1 (回踩日) | EMA10 > 前日EMA10 | EMA上升中 |
| Day 1 | 收盘价在EMA10±5%内 | 价格靠拢EMA |
| Day 1 | 最低价测试EMA | 低点触及EMA附近 |
| Day 2 (确认日) | 收盘 > Day 1 收盘 | 价格向上确认 |
| Day 2 | 收盘在波幅上半部 | 买盘强势 |
| Day 2 | 收盘 > EMA10 | 站上EMA |

**止损**：Day 1 最低价 × 0.99

**补充说明**：
- `cycle_detector.py` 第490-495行：收盘在EMA10±5%内（第105%限制为>1.05则失败）
- 实际代码：`if y_close > ema10 * 1.05: return False`

---

#### 2.1.3 Base n' Break（突破入场）⭐⭐⭐

**定义**：价格突破盘整区间。

**入场条件**：
1. 价格突破20日盘整高点
2. EMA10 向上

**止损**：EMA10 × 0.97（3% below EMA10）

**持仓**：每笔 $2,000（小于Wedge Pop/EMA Crossback的$5,000）

---

#### 2.1.4 Variant Patterns（变体形态）⭐⭐

**包含**：VCP、Cull Flag、Bull Pennant

**条件**：独立形态突破入场

---

### 2.2 做空信号

#### 2.2.1 Wedge Drop Short（楔形跌破做空）⭐⭐⭐⭐⭐

**触发条件**：
- `cycle_detector.classify() == CycleStage.WEDGE_DROP`
- 价格跌破 EMA10×0.92 或 < EMA20
- EMA10 和 EMA20 同时下降

**止损**：EMA20 × 1.02（允许2%穿透，空头止损在EMA20上方2%）

**持仓**：每笔 $5,000

---

#### 2.2.2 Exhaustion Short（衰竭做空）⭐⭐⭐⭐

**触发条件**：
- `cycle_detector.classify() == CycleStage.EXHAUSTION_EXTENSION`
- 价格 >10% 远离 EMA
- Gap Up ≥ 3%

**止损**：当日高点 × 1.02

**持仓**：每笔 $5,000

---

### 2.3 出场信号

| 出场类型 | 触发条件 | 动作 |
|---------|---------|------|
| EMA20跌破 | 收盘 < EMA20 × 0.98 | 全卖 |
| EMA10跌破 | 收盘 < EMA10 | 全卖 |
| Failed Breakout | 突破后10日内跌回95% | 全卖 |
| Extension卖出 | 第1/2/3次Extension高点回落5% | 卖20%/50%/100% |
| 时间止损 | 持有>90天且涨幅<10% | 全卖 |
| 3x Trapped | 价格反复贴近EMA20≥3次 | 全卖 |

---

## 三、市场环境过滤

系统根据指数（QQQ）与EMA20的关系将市场分为四档：

| 环境 | 条件 | 最大仓位 | 操作 |
|------|------|---------|------|
| **Quality** | QQQ > EMA20 | 190% | 满仓操作 |
| **Average** | QQQ ≈ EMA20 (±1%) | 50% | 3-5持仓，现金为王 |
| **Poor** | QQQ < EMA20 | 30% | 1-2持仓 |
| **Hostile** | 持续下跌 | 0% | 全现金 |

---

## 四、数据源

### 4.1 市场数据

| 数据源 | 优先级 | 用途 |
|-------|--------|------|
| **Alpaca Market Data (IEX)** | 主源 | 美股日线数据 |
| **Yahoo Finance API** | 备用 | Alpaca失败时补充 |
| **VIX GitHub** | 专用 | 波动率指数 |

### 4.2 本地缓存

- 路径：`data/cache/*.pkl`
- 永久缓存，无过期时间
- 支持清空：`clear_cache(symbol=None)` ⚠️ **警告：毁灭性操作**

### 4.3 数据限制

- **当前本地数据范围**：2026-01-02 ~ 2026-05-13
- **回测需要足够历史数据**：warmup需要300天预热

---

## 五、股票池

### 5.1 组合规则

```
最终股票池 = UNIVERSE.md（手动196只） ∪ 指数成分股 ∪ Alpaca自动池
```

### 5.2 手动股票池

- 路径：`UNIVERSE.md`
- 当前数量：196只
- 管理方式：直接编辑文件，增删行

---

## 六、持仓管理

### 6.1 仓位分配

| 信号类型 | 每笔金额 | 说明 |
|---------|---------|------|
| Wedge Pop | $5,000 | 初始建仓30% |
| EMA Crossback | $5,000 | 回踩加仓 |
| Base n' Break | $2,000 | 趋势延续轻仓 |
| Variant Patterns | $2,000 | 变体形态 |
| Wedge Drop Short | $5,000 | 做空 |
| Exhaustion Short | $5,000 | 做空 |

### 6.2 分批建仓

- **Batch 1**：Wedge Pop 触发后，首批30%仓位
- **Batch 2**：次日确认上涨后，加仓30%
- **Scale In**：EMA Crossback 可加仓至40%

---

## 七、回测结果（2026年）

**回测区间**：2026-01-02 ~ 2026-05-13（90个交易日）
**初始本金**：$50,000
**最终净值**：$61,643（**+23.3%**）

| 指标 | 数值 | 及格线 | 状态 |
|-----|------|--------|------|
| 胜率 | 42.9% | > 40% | ✓ |
| 盈亏比 | 2.70 | > 1.5 | ✓ |
| 最大回撤 | 9.4% | < 25% | ✓ |
| 年化收益 | **79.3%** | > 15% | ✓ |
| 夏普比率 | **3.34** | > 1.0 | ✓ |
| 每月信号数 | 109.9 | 2~10 | ✗ |

**综合评级：5/6 项达标**

---

## 八、已知问题

### 8.1 FN 信号误报（已确认）

**问题**：FN 在 2026-05-15 被报告为 EMA Crossback 买入信号，但实际上不满足条件。

**原因**：EMA Crossback 的条件2要求"回踩日收盘在EMA10±5%内"，即收盘/EMA10 ≤ 105%。

FN 2026-05-13：
- 回踩日收盘：$696.78
- EMA10：$662.27
- 比值：696.78/662.27 = **105.2%** > 105% → **条件失败**

但 live test 仍然报告了 FN 信号，说明策略代码中存在bug。

**建议修复**：检查 `cycle_detector.py` 第490-495行及 `oliver_kell_strategy.py` `_handle_ema_crossback` 的条件判断逻辑是否一致。

---

### 8.2 信号数量过多

- 每月信号数 109.9，远超标准（2~10）
- 原因：策略没有对每日最大信号数做严格限制
- 建议：增加 `max_signals` 参数或提高 RS 排名门槛

---

### 8.3 SLAB 信号时点问题

- SLAB 在 05-13 满足 EMA Crossback 条件，但因 live test 在 05-14 运行，以 05-14 作为"确认日"
- 如果 05-14 收盘 > 05-13 收盘，信号才会在 05-15 的报告中出现
- 这不是bug，是策略设计的正常行为

---

### 8.4 数据源限流

- Yahoo Finance 频繁返回 403 限流错误
- Alpaca 作为主源可靠，但不支持部分国际股票（LVMH、XNRG、9992.HK等）
- 建议：考虑 Polygon 或其他数据源作为补充

---

### 8.5 回测数据范围受限

- 本地缓存数据仅覆盖 2026-01-02 至今
- 完整的策略回测需要更长历史数据（warmup 300天）
- 当前回测结果仅供参考

---

## 九、输出报告

### 9.1 文件结构

```
output/v_oliver_kell/
├── signals.csv                    # 信号历史
├── backtest/                    # 回测报告
├── positions.json               # 当前持仓
└── YYYY-MM-DD/
    ├── 报告_Oliver Kell Cycle..._YYYY-MM-DD.md   # 日报
    └── 雷达_Oliver Kell Cycle..._YYYY-MM-DD.md   # 雷达报告
```

### 9.2 信号输出字段

| 字段 | 说明 |
|------|------|
| 日期 | 信号日期 |
| 股票 | 股票代码 |
| 信号 | 买入/卖出/做空/观望 |
| 强度(1-5) | 1-5星评级 |
| 触发原因 | 详细触发条件 |
| 参考止损 | 建议止损价格 |
| 持仓股数 | 手动填写 |

---

## 十、运行命令

```bash
# 实盘模式
uv run python main.py --mode live --strategy v_oliver_kell

# 回测模式
uv run python main.py --mode backtest --start 2026-01-01 --end 2026-05-13 --strategy v_oliver_kell

# 扫描股票池
uv run python main.py --mode scan

# 单独运行 live test
uv run python run_live_test.py
```

---

## 十一、配置文件

| 配置项 | 路径 | 说明 |
|-------|------|------|
| 策略参数 | `config.yaml` → `strategies.v_oliver_kell` | 入场/出场参数 |
| 股票池 | `UNIVERSE.md` | 手动股票池 |
| API密钥 | `.env` | Alpaca/Finnhub等 |

---

## 十二、EMA Crossback 完整计算示例（BVS）

**日期**：2026-05-13（确认日）/ 2026-05-12（回踩日）

| 项目 | Day 1 回踩日 (05-12) | Day 2 确认日 (05-13) |
|------|----------------------|---------------------|
| 收盘价 | $10.16 | $10.42 |
| 最低价 | $9.95 | - |
| EMA10 | 10.29 | 10.31 |
| 条件1: EMA10上升 | - | 10.31 > 10.29 ✓ |
| 条件2: 收盘在EMA10±5% | 10.16/10.29 = 98.8% ✓ | - |
| 条件3: 低点测试EMA | 9.95/10.29 = 96.7% ✓ | - |
| 条件4: 收盘>昨天收盘 | - | 10.42 > 10.16 ✓ |
| 条件5: 波幅上半部 | - | 10.42 ≥ 10.30 ✓ |
| 条件6: 收盘>EMA10 | - | 10.42 > 10.31 ✓ |

**止损**：Day 1 最低价 $9.95 × 0.99 = **$9.85**

---

*文档生成时间：2026-05-15*
