# Signal System Oliver — 项目开发说明书

> **版本**：2026-06-22
> **目标读者**：需要在另一台电脑上通过 Claude Code 复现本项目的开发者
> **当前在线策略**：`v_oliver_kell`（Oliver Kell "Cycle of Price Action"）
> **项目根目录**：`/Users/wubo/Desktop/codes/signal_system_Oliver`

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈与依赖](#2-技术栈与依赖)
3. [完整文件结构](#3-完整文件结构)
4. [架构总览](#4-架构总览)
5. [快速复现步骤（在新电脑上）](#5-快速复现步骤在新电脑上)
6. [配置详解](#6-配置详解)
7. [数据层](#7-数据层)
8. [股票池](#8-股票池)
9. [事件层](#9-事件层)
10. [策略层（v_oliver_kell）](#10-策略层v_oliver_kell)
11. [信号层](#11-信号层)
12. [回测引擎](#12-回测引擎)
13. [运行模式与命令](#13-运行模式与命令)
14. [日报与雷达报告](#14-日报与雷达报告)
15. [如何新增策略](#15-如何新增策略)
16. [持仓跟踪与持久化](#16-持仓跟踪与持久化)
17. [自动化与定时任务](#17-自动化与定时任务)
18. [关键设计原则与已知陷阱](#18-关键设计原则与已知陷阱)
19. [复现检查清单](#19-复现检查清单)

---

## 1. 项目概述

Signal System Oliver 是一个**事件驱动的美股交易信号系统**，以 Oliver Kell 的
《Cycle of Price Action》六阶段循环理论为核心，每日扫描股票池，输出以下信号：

| 方向 | 类型 | 强度 | 含义 |
|------|------|------|------|
| 买入 | Wedge Pop | ★★★★★ | 楔形突破 — 最佳买点 |
| 买入 | EMA Crossback | ★★★★☆ | 回踩 EMA 入场 |
| 买入 | Base n' Break | ★★★☆☆ | 盘整突破（趋势延续）|
| 买入 | Variant Patterns | ★★☆☆☆ | VCP / Bull Flag / Pennant |
| 做空 | Wedge Drop Short | ★★★★★ | 楔形跌破 |
| 做空 | Exhaustion Short | ★★★★☆ | 顶部衰竭 |
| 卖出 | Exit Signals | — | 7 级出场优先级 |
| 观望 | Watchlist | — | Reversal Extension / Base Tightening |

系统支持**实盘信号**（live）、**历史回测**（backtest）、**股票池扫描**（scan）三种运行模式，
并提供**每日 Markdown 日报**与**Oliver Kell 雷达报告**。

---

## 2. 技术栈与依赖

### 2.1 运行环境

- **Python**：3.13+
- **包管理**：`uv`（推荐）或 `pip`
- **操作系统**：macOS（用 `osascript` 做通知）、Linux 也可运行（去掉 macOS 通知即可）

### 2.2 核心依赖（pyproject.toml）

```
alpaca-py      ≥ 0.43.2   # 美股主数据源（IEX feed 免费）
yfinance       ≥ 1.2.0    # 美股/国际股备用源
pandas         ≥ 3.0.1
numpy          ≥ 2.4.2
pyyaml         ≥ 6.0.3
python-dotenv  ≥ 1.2.2
requests       ≥ 2.32.5
akshare        ≥ 1.18.47  # 港股/中文市场（已声明，未启用）
matplotlib     ≥ 3.10.8
notebook       ≥ 7.5.5
```

### 2.3 API 密钥（.env）

| 密钥 | 用途 | 是否必须 |
|------|------|---------|
| `ALPACA_API_KEY` | 美股实时/历史数据、新闻股票池 | **必须** |
| `ALPACA_SECRET_KEY` | 同上 | **必须** |
| `ALPACA_BASE_URL` | 默认 `https://paper-api.alpaca.markets` | 否 |
| `ALPHA_VANTAGE_API_KEY` | 2010-2016 早期历史数据 | 可选 |
| `FINNHUB_API_KEY` | EPS 季度数据 | 可选 |
| `POLYGON_API_KEY` | 资产负债表 fallback | 可选 |
| `FMP_API_KEY` | 财务数据 fallback | 可选 |

> 模板在 `.env.example`。Alpaca 免费版够用：https://alpaca.markets/

---

## 3. 完整文件结构

```
signal_system_Oliver/
├── main.py                      # CLI 入口（live/backtest/scan）
├── config.yaml                  # 全局配置
├── pyproject.toml               # Python 项目元数据
├── requirements.txt             # pip 依赖（与 pyproject 略有不同）
├── uv.lock                      # uv 锁定文件
├── .env.example                 # 密钥模板
│
├── README.md                    # 顶层项目说明
├── HANDOVER.md                  # 历史交接文档（旧项目，已过时）
├── USAGE.md                     # 用户使用手册（部分过时）
├── HOW_TO_ADD_STRATEGY.md       # 新增策略教程
│
├── data/                        # 数据获取层
│   ├── fetcher.py               # ★ 三层缓存 + Alpaca/Yahoo/VIX
│   ├── fundamentals.py          # Alpha Vantage + Finnhub EPS
│   ├── balance_sheet.py         # 资产负债表 + NCAV 计算
│   ├── sec_edgar.py             # SEC EDGAR XBRL 解析
│   ├── finnhub_metrics.py       # Finnhub 财务指标
│   ├── fmp_financials.py        # FMP 财报
│   ├── polygon_financials.py    # Polygon 财报
│   ├── refresh_stale.py         # cron 用：补下载过期数据
│   ├── index_cache.json         # 指数成分股缓存
│   ├── cache/                   # ★ 持久化数据缓存（*.pkl）
│   │                             # 不可删除！丢失后 Yahoo 限流无法恢复
│   └── cache_backup/            # 备份（可清空）
│
├── universe/                    # 股票池管理层
│   ├── manager.py               # 合并 UNIVERSE + 指数 + 自动池
│   ├── index_fetcher.py         # S&P 500 / Nasdaq 100 / Russell 2000
│   ├── alpaca_fetcher.py        # Alpaca 新闻 API 自动池
│   ├── sa_scanner.py            # Seeking Alpha Quant Rating
│   └── updater.py               # 把 SA 评分高股票写入 UNIVERSE.md
│
├── events/                      # 事件层
│   ├── base.py                  # Event / BarEvent / SignalEvent
│   └── queue.py                 # EventQueue（FIFO 线程安全）
│
├── strategies/                  # 策略层
│   ├── base.py                  # StrategyBase 抽象基类
│   ├── registry.py              # 策略注册表
│   └── v_oliver_kell/           # ★ 当前在线策略
│       ├── __init__.py
│       ├── oliver_kell_strategy.py   # ★ 主策略类（1158 行）
│       ├── cycle_detector.py         # 六阶段识别
│       ├── wedge_finder.py           # 楔形检测
│       ├── market_environment.py     # QQQ 状态四档
│       ├── scale_in.py               # 分批建仓
│       └── exit_manager.py           # 出场管理
│
├── signals/                     # 信号输出层
│   ├── generator.py             # 控制台 + CSV 输出
│   ├── report.py                # 每日 Markdown 日报
│   ├── oliver_kell_radar_report.py  # ★ 雷达报告
│   ├── watchlist_scanner.py     # Reversal/Base 观察池
│   ├── positions.py             # 持仓 JSON 持久化
│   └── log_generator.py         # 全策略信号汇总
│
├── backtest/                    # 回测引擎
│   ├── engine.py                # ★ BacktestEngine + Trade + BacktestResult
│   ├── extended_backtest.py     # 扩展指标
│   ├── full_backtest_v_eps_v2.py
│   └── analyze_v2_2023.py
│
├── tests/
│   └── v_oliver_kell/           # 单元测试
│       ├── test_cycle_detector.py
│       ├── test_exit_manager.py
│       ├── test_market_environment.py
│       ├── test_scale_in.py
│       ├── test_strategy_integration.py
│       └── test_wedge_finder.py
│
├── docs/                        # 项目文档
│   ├── PRD_v_oliver_kell_2026-05-15_v2.md   # ★ 产品 PRD（必读）
│   ├── PRD_v_oliver_kell_2026-05-15_v1.md   # 旧版 PRD
│   ├── strategies/                         # 旧策略文档（历史）
│   └── ...
│
├── 实施计划/                    # 中文实施计划
│
├── scripts/
│   └── batch_fetch_eps.py       # 批量预取 EPS（v_eps_v2 时代）
│
├── output/                      # 运行时输出（自动创建）
│   ├── v_oliver_kell/
│   │   ├── signals.csv          # 信号历史
│   │   ├── positions.json       # 持仓
│   │   ├── backtest/            # 回测报告
│   │   └── YYYY-MM-DD/
│   │       ├── 报告_*.md
│   │       └── 雷达_*.md
│   ├── shared/                  # 跨策略数据
│   └── SIGNALS_LOG.md
│
├── UNIVERSE.md                  # ★ 手动股票池（唯一来源，301 只美股）
├── UNIVERSE_EPS_TEST.md         # 备用股票池（历史）
├── UNIVERSE_RUSSELL2000.md      # Russell 2000 备用池
├── UNIVERSE_test.md             # 单元测试用
│
├── Oliver_Kell_Victory_in_Stock_Trading.pdf   # 策略原文
├── run_daily.sh                 # macOS 每日运行脚本
├── com.sepa.signal.daily.plist  # launchd 配置
│
└── (历史脚本：backtest_2026_*.py, diag_*.py, debug_*.py 等)
    # 这些是开发/调试用的脚本，不影响主线运行
```

---

## 4. 架构总览

### 4.1 整体数据流

```
                         ┌─────────────────┐
                         │   UNIVERSE.md   │  ← 用户唯一手动编辑
                         │  301 只美股池   │
                         └────────┬────────┘
                                  │
                                  ▼
   ┌──────────┐    ┌──────────────────────────────┐
   │ Alpaca   │───▶│     universe/manager.py      │──┐
   │ News API │    │  (合并:手动 + 指数 + 自动池)  │  │
   └──────────┘    └──────────────────────────────┘  │
                                                     │
   ┌──────────┐    ┌──────────────────────────────┐  │
   │ Wikipedia│───▶│  universe/index_fetcher.py   │──┤
   └──────────┘    └──────────────────────────────┘  │
                                                     │
                                                     ▼
                                          ┌──────────────────┐
                                          │   最终股票池      │
                                          │  ~301-500 只     │
                                          └────────┬─────────┘
                                                   │
                                                   ▼
   ┌──────────┐    ┌──────────────────────────────┐
   │ Alpaca   │───▶│      data/fetcher.py         │
   │ IEX Feed │    │   (三层缓存:本地+增量+全量)  │──▶ market_data: dict
   └──────────┘    └──────────────────────────────┘
   ┌──────────┐              ▲
   │ Yahoo    │──────────────┘  (备用)
   └──────────┘
                          market_data (dict[symbol → DataFrame])
                                   │
                                   ▼
   ┌────────────────────────────────────────────────────────┐
   │             strategies/v_oliver_kell/                  │
   │  ┌──────────────────┐  ┌────────────────────────┐    │
   │  │ cycle_detector   │  │  market_environment    │    │
   │  │  (六阶段识别)     │  │  (Quality/Avg/Poor/    │    │
   │  │                  │  │   Hostile)             │    │
   │  └──────────────────┘  └────────────────────────┘    │
   │  ┌──────────────────┐  ┌────────────────────────┐    │
   │  │ wedge_finder     │  │  scale_in              │    │
   │  │  (楔形检测)       │  │  (Batch 1/2/Full)      │    │
   │  └──────────────────┘  └────────────────────────┘    │
   │  ┌──────────────────────────────────────────┐        │
   │  │     exit_manager (7级出场优先级)          │        │
   │  └──────────────────────────────────────────┘        │
   │  ┌──────────────────────────────────────────┐        │
   │  │  oliver_kell_strategy (主类)              │        │
   │  │   run_date(date, queue) → 产生 SignalEvent│       │
   │  └──────────────────────────────────────────┘        │
   └─────────────────────┬──────────────────────────────────┘
                         │  SignalEvent 列表
                         ▼
                  ┌──────────────┐
                  │  EventQueue  │  (events/queue.py)
                  └──────┬───────┘
                         │
            ┌────────────┼────────────┐
            ▼            ▼            ▼
   ┌─────────────┐ ┌──────────┐ ┌────────────────┐
   │ generator   │ │ 报告     │ │ 雷达报告       │
   │ CSV+控制台  │ │  Markdown│ │ (OK 专属)     │
   └─────────────┘ └──────────┘ └────────────────┘
            │            │            │
            ▼            ▼            ▼
            └────────────┴────────────┘
                         │
                         ▼
                  output/v_oliver_kell/
                  ├─ signals.csv
                  ├─ positions.json
                  ├─ YYYY-MM-DD/报告.md
                  └─ YYYY-MM-DD/雷达.md
```

### 4.2 核心设计原则

1. **策略插件化**：所有策略继承 `StrategyBase`，注册到 `strategies/registry.py`
2. **事件驱动**：数据/策略/输出三模块通过 `EventQueue` 解耦
3. **三层数据缓存**：本地 pickle → 增量更新 → 全量下载
4. **股票池唯一来源**：`UNIVERSE.md` 直接编辑，不通过 config.yaml
5. **回测 = 策略观察者**：引擎不改策略代码，只读取 SignalEvent
6. **可复现**：固定时间窗口、固定股票池，输出应可重现

---

## 5. 快速复现步骤（在新电脑上）

### 5.1 系统要求

- macOS 12+ / Linux / WSL2
- Python 3.13+
- `uv`（推荐）或 `pip`
- 至少 5GB 磁盘空间（`data/cache/*.pkl` 约 3-4GB）

### 5.2 安装步骤

```bash
# 1. 克隆/复制整个项目
cd /path/to/signal_system_Oliver

# 2. 安装 uv（如果还没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 创建虚拟环境并安装依赖
uv sync

# 4. 复制环境变量模板
cp .env.example .env
# 编辑 .env，填入：
#   ALPACA_API_KEY=...
#   ALPACA_SECRET_KEY=...

# 5. 验证安装
uv run python -c "from data.fetcher import fetch; print('OK')"

# 6. 跑一次实盘信号（生成第一份报告）
uv run python main.py --mode live --strategy v_oliver_kell
```

### 5.3 首次运行的预期行为

| 阶段 | 现象 | 耗时 |
|------|------|------|
| 加载 UNIVERSE.md | 301 只美股 | < 1s |
| 下载 Alpaca 历史数据 | 首次全量下载，生成 `data/cache/*.pkl` | 3-8 分钟（取决于网速）|
| 运行策略 | 计算 301 只股票的六阶段 | 30-60 秒 |
| 生成报告 | Markdown 写到 `output/v_oliver_kell/YYYY-MM-DD/` | < 1s |
| 雷达报告 | 扫描 watchlist 候选股 | 5-10 秒 |

### 5.4 重要提示

- **不要清空 `data/cache/`**！清空后 Yahoo Finance 限流无法重新下载，几个月历史数据将永久丢失
- `data/cache_backup/` 是历史备份，可清理
- `.env` 不要提交到 git

---

## 6. 配置详解

### 6.1 `config.yaml` 结构

```yaml
# 默认策略（main.py 未指定 --strategy 时使用）
active_strategy: v_oliver_kell

# 股票池自动扩展
auto_universe:
  source: alpaca              # 用 Alpaca 新闻 API 抓取被提及的股票
  initial_lookback_days: 365  # 首次运行回溯天数
  max_age_days: 365           # 超过 N 天未被提及就移出
  include_indices: []         # 可选: ["sp500", "nasdaq100", "russell2000"]

# 数据获取
data:
  timeframe: "1d"
  history_days: 3652          # ≈ 10 年，覆盖多个牛熊周期

# 策略参数
strategies:
  v_oliver_kell:              # 与 registry.py 中的 key 对应
    name: "Oliver Kell Cycle of Price Action"
    description: "..."
    wedge_lookback: 20        # 楔形识别回看天数
    base_lookback: 20         # 盘整识别回看天数
    index_symbol: "QQQ"       # 用 QQQ 判断市场环境
    require_wedge_pop_first: true
    initial_stop_pct: 0.02    # 初始止损 2%
    trim_gain_threshold: 1.0  # 涨幅 100% 触发减仓
    trailing_ema_period: 20   # 追踪止盈用 20 EMA
    time_stop_days: 60        # 时间止损 60 天

# 输出
output:
  print_to_console: true
  save_to_csv: true

# 股票池扫描（--mode scan）
scan:
  sa_quant_min: 4.5           # SA Quant 评分阈值（Strong Buy）
  min_market_cap_b: 1.0       # 最小市值 $1B
  max_new_per_run: 30         # 每次最多新增 30 只
  request_delay_seconds: 1.2  # 请求间隔防限流
```

### 6.2 配置切换策略

```bash
# 临时切换
uv run python main.py --mode live --strategy v_oliver_kell

# 永久切换：修改 config.yaml
active_strategy: v_oliver_kell
```

---

## 7. 数据层

### 7.1 核心：`data/fetcher.py`

**三层缓存策略**：

```
┌──────────────────────────────────────────────────────┐
│  Tier 1: 本地缓存新鲜（live ≤0天 / backtest ≤3天）  │
│          → 直接使用，零网络请求                      │
├──────────────────────────────────────────────────────┤
│  Tier 2: 本地有历史但过期                            │
│          → 增量下载 delta，合并后写回本地            │
├──────────────────────────────────────────────────────┤
│  Tier 3: 本地无数据或历史不足                        │
│          → 全量下载（Alpaca 主，Yahoo 备）          │
└──────────────────────────────────────────────────────┘
```

**数据源优先级**：

| 数据类型 | 主源 | 备用 | 备注 |
|---------|------|------|------|
| 美股日线 | Alpaca IEX | Yahoo Finance | IEX 免费 |
| 非美股 | （不支持）| Yahoo Finance | 经常 403 |
| VIX 指数 | GitHub datasets | — | 1990-至今 |
| EPS | Finnhub | Alpha Vantage | 季度 |
| 资产负债表 | SEC EDGAR | Polygon | XBRL JSON |

**关键函数**：

```python
from data.fetcher import fetch

market_data = fetch(
    symbols=["AAPL", "NVDA", "MSFT"],
    history_days=365,
    live_mode=True,           # True=实盘要求当日数据
    end_date=None             # 回测时传入回测结束日
)
# 返回 {symbol: DataFrame with columns [open,high,low,close,volume]}
# 索引为 UTC DatetimeIndex
```

### 7.2 yfinance 双 bar 问题

`yfinance` 对美股返回每日两个 bar：
- `05:00 UTC` = 前一日盘后
- `14:30 UTC` = 当日收盘

**修复策略**（在 `strategies/base.py` 和 `backtest/engine.py`）：

```python
def _get_close_for_date(df, date):
    """找到与 date 日历日期匹配的最后一行"""
    # 不能用 iloc[-1]，必须按日历日期匹配
    df_sliced = self._slice_to_date(df, date)
    cutoff = date.normalize() + pd.Timedelta(days=1)
    return df_sliced[df_sliced.index <= cutoff].iloc[-1]
```

⚠️ **复现时**：所有读取价格的地方都必须用日历日期匹配，不要直接用 `iloc[-1]`。

### 7.3 销毁性操作警告

| 操作 | 后果 | 是否可逆 |
|------|------|---------|
| `clear_cache(symbol)` | 删除单只股票本地数据 | 是（重新下载）|
| `clear_cache()` 无参数 | **删除所有本地数据** | **否**（Yahoo 限流无法恢复）|
| 删除 `data/cache/*.pkl` | 同上 | **否** |
| 删除 `data/cache_backup/` | 丢失备份 | 否 |

**承诺**：未经用户明确授权，绝不执行 `clear_cache()` 或删除 `data/cache/`。

---

## 8. 股票池

### 8.1 组成

```
最终股票池 = UNIVERSE.md（手动 301 只）∪ 指数成分股 ∪ Alpaca 新闻自动池
```

### 8.2 UNIVERSE.md 格式（唯一手动来源）

```markdown
# 股票池主清单 (UNIVERSE)

## 当前手动池总数：301 只（美股301）

## 板块 A：Oliver Kell 策略股票池

| 代码 | 公司 | 简介 |
|------|------|------|
| QQQ | Invesco QQQ | Oliver Kell 池（市场环境判断） |
| COF | Capital One | Oliver Kell 池 |
| ... |

## 待移出记录

（暂无）
```

**规则**：
- 表格行格式 `| TICKER | 公司名 | 简介 |`
- 解析到 `## 待移出记录` 标题时停止（之后的股票不计入正式池）
- 在代码块（``` ``` ```）内的内容不解析
- 文件不存在时返回空池

### 8.3 指数成分股

- `sp500` / `nasdaq100`：从 Wikipedia 抓取，永久缓存到 `data/index_cache.json`
- `russell2000`：从本地 `UNIVERSE_RUSSELL2000.md` 读取

启用方式：

```yaml
auto_universe:
  include_indices: ["sp500", "nasdaq100"]  # 加入这 2 个指数
```

### 8.4 自动池（Alpaca 新闻）

- 首次运行：抓取过去 365 天新闻
- 后续运行：只抓昨天
- 超过 `max_age_days`（默认 365）未被提及则自动移出

---

## 9. 事件层

### 9.1 事件类型

```python
from events import BarEvent, SignalEvent, EventType

# K线数据事件
bar = BarEvent.create(
    symbol="AAPL",
    timestamp=datetime.now(),
    open_=150.0, high=152.0, low=149.0, close=151.5, volume=1_000_000
)

# 交易信号事件
sig = SignalEvent.create(
    symbol="AAPL",
    timestamp=datetime.now(),
    direction="buy",          # buy / sell / short / watch
    strength=5,                # 1-5
    reason="Wedge Pop, EMA10+EMA20 收敛后突破",
    stop_loss=148.50,
    shares=33.0,               # 持仓股数（用户填）
    position_dollar=5000.0,    # 仓位美元
    cycle_stage="wedge_pop",
    current_price=151.5
)
```

### 9.2 EventQueue（FIFO）

```python
from events import EventQueue
q = EventQueue()
q.put(bar)
q.put(sig)
while not q.empty():
    event = q.get(timeout=0.1)
    if event is None: break
    # process event
```

---

## 10. 策略层（v_oliver_kell）

### 10.1 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `oliver_kell_strategy.py` | 1158 | 主类：买入/卖出/做空信号生成 |
| `cycle_detector.py` | 1393 | 六阶段识别 + 形态检测 |
| `wedge_finder.py` | 191 | 楔形（contracting/expanding）检测 |
| `market_environment.py` | 102 | QQQ 四档状态分类 |
| `scale_in.py` | 255 | 分批建仓（Batch 1/2/Full） |
| `exit_manager.py` | 224 | 7 级出场优先级 + 减仓 |

### 10.2 CycleStage 枚举

```python
class CycleStage(Enum):
    REVERSAL_EXTENSION   = "reversal_extension"     # 反转延伸
    WEDGE_POP            = "wedge_pop"              # 楔形突破
    EMA_CROSSBACK        = "ema_crossback"          # EMA 回踩
    BASE_N_BREAK         = "base_n_break"           # 盘整突破
    EXHAUSTION_EXTENSION = "exhaustion_extension"   # 顶部衰竭
    WEDGE_DROP           = "wedge_drop"             # 楔形跌破
    UNKNOWN              = "unknown"
```

### 10.3 买入信号四类型

#### 10.3.1 Wedge Pop ★★★★★
**三步前置条件**：
1. EMA 压力测试：价格曾反弹至 EMA20 附近被拒绝
2. EMA 下方盘整：EMA10 和 EMA20 在 10 天内间距收窄 10%+
3. 放量突破：EMA 向上，价格突破

**入场**：
- 突破日收盘 × 0.98 = 止损
- 仓位：$5,000（20%）

#### 10.3.2 EMA Crossback ★★★★☆
**Day 1 (回踩日)**：
- EMA10 > 前日 EMA10（EMA 上升）
- 收盘价在 EMA10 ±5% 内
- 最低点在 EMA10 ±5% 内

**Day 2 (确认日)**：
- 收盘 > Day 1 收盘
- 收盘 ≥ 低点 + (高点-低点) × 50%
- 收盘 > EMA10

**止损**：回踩日最低价 × 0.99

#### 10.3.3 Base n' Break ★★★☆☆
- 价格在 EMA20 上方
- 10-20 天盘整
- 今日收盘 > 盘整期最高点
- 60%+ 日子在 EMA10 上方
- 盘整区间 < 中间价 × 15%
- 价格相对 EMA10 偏离 < 2%

**止损**：EMA10 × 0.97

#### 10.3.4 Variant Patterns ★★☆☆☆
- **VCP**：近 20 天分 3 段，波动率递减
- **Bull Flag**：前期 15%+ 涨幅 + 5-10 天盘整
- **Bull Pennant**：旗杆 + 三角形收缩

### 10.4 做空信号

- **Wedge Drop Short**：价格 < EMA10 × 0.92，EMA10/20 双降，止损 EMA20 × 1.02
- **Exhaustion Short**：CycleStage == EXHAUSTION + Gap Up ≥ 3% + 远离 EMA > 10%

### 10.5 7 级出场优先级

```
优先级 1: Wedge Drop（CycleStage == WEDGE_DROP）→ 全卖
优先级 2: 硬止损（价格 < 入场价 × 0.92）         → 全卖
优先级 3: Ignite Bar 止损                          → 全卖
优先级 4: EMA20 跌破（收盘 < EMA20 × 0.98）        → 全卖
优先级 5: 假突破（10 日内跌回突破价 × 0.95）       → 全卖
优先级 6: Extension 减仓                            → 20%/50%/100%
优先级 7: 时间止损（>60-90 天，涨幅<5-10%）        → 全卖
```

### 10.6 市场环境过滤（MarketEnvironment）

| 环境 | 条件 | 最大仓位 | 最多信号数 |
|------|------|---------|-----------|
| Quality | QQQ > EMA20 × 1.01 | 190% | 10 |
| Average | QQQ 在 EMA20 ±1% | 50% | 5 |
| Poor | QQQ < EMA20 × 0.99 | 30% | 2 |
| Hostile | 10 日内 8 天收跌 | 0% | 0 |

---

## 11. 信号层

### 11.1 CSV 输出

路径：`output/v_oliver_kell/signals.csv`

```csv
日期,股票,信号,强度(1-5),触发原因,参考止损,持仓股数
2026-05-14,AAPL,买入,5,Wedge Pop 突破,$148.50,—
2026-05-14,MSFT,卖出,—,止损 8% 触发,$420.00,33 股
```

### 11.2 日报 Markdown

路径：`output/v_oliver_kell/YYYY-MM-DD/报告_*.md`

包含：当日所有买入/卖出/做空信号 + 持仓状态 + 触发原因。

### 11.3 雷达报告

路径：`output/v_oliver_kell/YYYY-MM-DD/雷达_*.md`

包含：
- 买入/做空/出场信号清单
- Watchlist 候选股（Reversal Extension + Base Tightening）

---

## 12. 回测引擎

### 12.1 启动方式

```bash
uv run python main.py --mode backtest \
    --start 2026-01-01 --end 2026-05-13 \
    --strategy v_oliver_kell \
    --position-size 5000 --initial-capital 50000
```

### 12.2 关键参数

| 参数 | 默认 | 说明 |
|------|------|------|
| `--start` | 必须 | YYYY-MM-DD |
| `--end` | 必须 | YYYY-MM-DD |
| `--position-size` | 1000 | 每笔固定金额（美元） |
| `--initial-capital` | 50000 | 初始本金 |
| `--split` | False | 自动分样本内/外 |
| `--save-signals` | False | 把买入信号也写 signals.csv |

### 12.3 评估指标

| 指标 | 及格线 | 计算方法 |
|------|--------|---------|
| 胜率 | > 40% | 盈利笔数 / 总笔数 |
| 盈亏比 | > 1.5 | 平均盈利% / 平均亏损% |
| 最大回撤 | < 25% | equity_curve 累积最大跌幅 |
| 每月信号数 | 2~10 | 总信号 / 月数 |
| 年化收益 | > 15% | (期末/期初)^(1/年) - 1 |
| 夏普比率 | > 1.0 | 日均收益/日波动 × √252 |

**及格数 ≥ 5/6** 视为策略合格。

### 12.4 已知回测数据范围

- 当前本地数据：2026-01-02 ~ 2026-05-13（视股票而定）
- 回测预热需求：300 天
- 长周期回测需先扩充 cache

---

## 13. 运行模式与命令

### 13.1 实盘信号

```bash
# 单策略
uv run python main.py --mode live --strategy v_oliver_kell

# 跑所有策略
uv run python main.py --mode live --all-strategies

# 用包装脚本
uv run python run_live_test.py
```

**输出**：
- 控制台信号表
- `output/v_oliver_kell/signals.csv`（追加）
- `output/v_oliver_kell/YYYY-MM-DD/报告_*.md`
- `output/v_oliver_kell/YYYY-MM-DD/雷达_*.md`
- `output/v_oliver_kell/positions.json`（更新持仓）

### 13.2 回测

```bash
# 基础回测
uv run python main.py --mode backtest \
    --start 2026-01-01 --end 2026-05-13

# 自动分样本内/外
uv run python main.py --mode backtest \
    --start 2026-01-01 --end 2026-05-13 --split

# 固定金额模型（默认）
uv run python main.py --mode backtest \
    --start 2026-01-01 --end 2026-05-13 \
    --position-size 5000 --initial-capital 50000
```

### 13.3 股票池扫描

```bash
# 实际写入 UNIVERSE.md
uv run python main.py --mode scan

# 只打印不修改
uv run python main.py --mode scan --dry-run
```

把 SA Quant 评分 ≥ 4.5 的新股票写入 `UNIVERSE.md` 的"自动扫描新增"节。

---

## 14. 日报与雷达报告

### 14.1 触发时机

每次 `live` 模式运行后自动生成。

### 14.2 报告内容

- **日报**（`报告_*.md`）：今日买入/卖出/做空信号 + 持仓摘要
- **雷达**（`雷达_*.md`）：信号 + Watchlist 候选（Reversal Extension / Base Tightening）

### 14.3 路径

```
output/v_oliver_kell/YYYY-MM-DD/报告_Oliver Kell Cycle of Price Action_YYYY-MM-DD.md
output/v_oliver_kell/YYYY-MM-DD/雷达_Oliver Kell Cycle of Price Action_YYYY-MM-DD.md
```

---

## 15. 如何新增策略

### 15.1 三步流程

1. **创建策略包**：`strategies/vN_xxx/`
2. **实现策略类**（继承 `StrategyBase`）
3. **注册到 `strategies/registry.py`**
4. **在 `config.yaml` 添加配置段**

### 15.2 最小策略模板

```python
# strategies/vN_xxx/my_strategy.py
from datetime import datetime
import pandas as pd
from events import EventQueue, SignalEvent
from strategies.base import StrategyBase


class MyStrategy(StrategyBase):
    strategy_id = "vN_xxx"          # 必须唯一
    strategy_name = "我的策略"

    def __init__(self, strategy_config, market_data, live_mode=False):
        super().__init__(strategy_config, market_data)
        self.cfg = strategy_config
        self.positions = {}  # symbol -> Position dataclass

    def run_date(self, date: datetime, queue: EventQueue) -> list:
        signals = []
        for symbol, df in self.market_data.items():
            if symbol in ("SPY", "QQQ", "^VIX"):
                continue
            df_to_date = self._slice_to_date(df, date)
            if len(df_to_date) < 60:
                continue
            # ... 你的逻辑 ...
            # if 信号:
            #     sig = SignalEvent.create(...)
            #     queue.put(sig)
            #     signals.append(sig)
        return signals
```

### 15.3 注册

```python
# strategies/registry.py
from strategies.vN_xxx.my_strategy import MyStrategy

STRATEGY_REGISTRY: dict[str, type] = {
    "v_oliver_kell": OliverKellStrategy,
    "vN_xxx": MyStrategy,            # ← 加这行
}
```

### 15.4 配置

```yaml
# config.yaml
strategies:
  vN_xxx:
    name: "我的策略"
    # ... 你的参数 ...
```

### 15.5 运行

```bash
uv run python main.py --mode live --strategy vN_xxx
```

---

## 16. 持仓跟踪与持久化

### 16.1 文件位置

```
output/v_oliver_kell/positions.json
```

### 16.2 格式

```json
{
  "AAPL": {
    "symbol": "AAPL",
    "entry_price": 150.0,
    "entry_date": "2026-05-14T00:00:00+00:00",
    "highest_price": 155.0,
    "days_held": 10,
    "shares": 33
  }
}
```

### 16.3 用户编辑规则

- **删除某行**：取消对该仓位的跟踪（你已手动平仓）
- **修改 entry_price**：调整为实际买入价
- **修改 highest_price**：更新追踪止盈的最高价
- **修改 shares**：更新持仓股数（计算卖出建议用）
- **手动添加一行**：跟踪自己加仓的股票

### 16.4 跨天追踪逻辑（main.py）

```python
saved_positions = load_positions(strategy_id)  # 读 JSON
strategy.positions = saved_positions
pre_run_snapshot = dict(strategy.positions)  # 快照

strategy.run_date(today, queue)  # 出场信号会自动删除 strategy.positions[symbol]

# 恢复被自动删除的持仓（用户未确认平仓前，持续提醒）
for symbol, pos in pre_run_snapshot.items():
    if symbol not in strategy.positions:
        strategy.positions[symbol] = pos

save_positions(strategy.positions, strategy_id)  # 写回
```

---

## 17. 自动化与定时任务

### 17.1 launchd（macOS）

配置文件：`com.sepa.signal.daily.plist`

```xml
<key>StartCalendarInterval</key>
<dict>
  <key>Hour</key><integer>5</integer>
  <key>Minute</key><integer>30</integer>
</dict>
```

每天北京时间 05:30 触发（覆盖美股收盘后 30 分钟）。

### 17.2 安装方式

```bash
cp com.sepa.signal.daily.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sepa.signal.daily.plist
```

### 17.3 包装脚本

`run_daily.sh`：
- 跳过周末
- 创建每日日志 `output/daily_YYYY-MM-DD.log`
- 跑完发 macOS 通知（osascript）

### 17.4 Linux 替代

用 cron：

```bash
30 5 * * 1-5 cd /path/to/signal_system_Oliver && uv run python main.py --mode live --strategy v_oliver_kell >> output/daily_$(date +\%F).log 2>&1
```

---

## 18. 关键设计原则与已知陷阱

### 18.1 必须遵守的"不要做"清单

❌ **不要**清空 `data/cache/*.pkl`（Yahoo 限流无法恢复）
❌ **不要**直接修改 `UNIVERSE.md` 之外的股票池来源
❌ **不要**用 `iloc[-1]` 取"今日收盘价"（双 bar 问题）
❌ **不要**改策略参数不告诉用户（代码即策略）
❌ **不要**擅自扩大回测时间范围
❌ **不要**TaskOutput 返回后凭印象汇报（必须先 Read 完整输出文件）

### 18.2 必须遵守的"要做"清单

✅ 任何破坏性操作前先 `ls` / `cat` 确认影响范围
✅ 跑回测前先确认时间窗口得到用户同意
✅ 持仓/股票池变化先报告再写入
✅ 单元测试覆盖核心逻辑（见 `tests/v_oliver_kell/`）
✅ 改策略前先读 `docs/PRD_v_oliver_kell_2026-05-15_v2.md`

### 18.3 已知 Bug / 不一致（来自 PRD 第 8 章）

| # | 问题 | 位置 |
|---|------|------|
| 8.1 | `BATCH1_PCT=0.20` 但文档说 25-35% | scale_in.py |
| 8.2 | 时间止损：config=60天 + ExitManager=60天涨幅<5% + _check_exits=90天涨幅<10% | 多处 |
| 8.3 | Base n' Break 第 1 次 Extension 减仓 50%（通用规则是 20%）| oliver_kell_strategy.py |
| 8.4 | 所有成交量检查已移除（IEX 限制） | cycle_detector.py |
| 8.5 | 每月信号数 109.9，远超 2~10 标准 | 需加 max_signals 限制 |
| 8.6 | Yahoo Finance 频繁 403 | 已有 Alpaca 主源 |

### 18.4 量化复现注意事项

- **同一日期 + 同一股票池 + 同一策略** → 输出必须一致
- Yahoo 限流会导致数据不全 → 复现前确认 `data/cache/` 完整
- Alpaca IEX 数据偶有缺失（如拆股当天）→ 引擎会跳过该日

---

## 19. 复现检查清单

在新电脑上按顺序执行以下步骤，每步完成后打勾：

### 19.1 环境

- [ ] Python 3.13+ 已安装（`python --version`）
- [ ] `uv` 已安装（`uv --version`）
- [ ] 至少 5GB 磁盘空间

### 19.2 项目

- [ ] 整个 `signal_system_Oliver/` 目录已复制
- [ ] 包含 `data/cache/*.pkl`（约 4000 个文件，3-4GB）
- [ ] 包含 `UNIVERSE.md`（301 只美股）
- [ ] 包含 `output/` 目录（可为空，但需要存在权限）

### 19.3 配置

- [ ] `.env` 文件已创建
- [ ] `ALPACA_API_KEY` 已填入
- [ ] `ALPACA_SECRET_KEY` 已填入
- [ ] `ALPACA_BASE_URL=https://paper-api.alpaca.markets`

### 19.4 依赖

- [ ] `uv sync` 成功（无 ERROR）
- [ ] `uv run python -c "import alpaca, pandas, yaml"` 无异常

### 19.5 第一次运行

- [ ] `uv run python run_live_test.py` 跑通
- [ ] 看到 "实盘模式" 启动信息
- [ ] 看到 "Step 1/3 更新股票池..." 等 3 个步骤
- [ ] 看到信号报告（买入/卖出/做空/观望）
- [ ] `output/v_oliver_kell/YYYY-MM-DD/报告_*.md` 已生成
- [ ] `output/v_oliver_kell/positions.json` 已创建

### 19.6 回测验证

- [ ] `uv run python main.py --mode backtest --start 2026-01-01 --end 2026-05-13` 跑通
- [ ] 控制台打印 BacktestResult 报告
- [ ] `output/v_oliver_kell/backtest/回测报告_*.md` 已生成
- [ ] Sharpe > 1.0, 胜率 > 40% 等指标与 PRD 一致

### 19.7 单元测试

- [ ] `uv run pytest tests/v_oliver_kell/` 全部通过

### 19.8 自动化

- [ ] launchd plist 已加载（macOS）
- [ ] 次日 05:30 自动跑出信号（如非周末）

---

## 附录 A：关键常量速查

| 常量 | 值 | 出处 |
|------|---|------|
| WARMUP_DAYS | 300 | backtest/engine.py |
| BATCH1_PCT | 0.20 | strategies/v_oliver_kell/scale_in.py |
| BATCH2_PCT | 0.10 | 同上 |
| INITIAL_STOP_PCT | 0.02 | 同上 |
| Wedge lookback | 20 | config.yaml + cycle_detector |
| Base lookback | 20 | 同上 |
| Time stop (config) | 60 天 | config.yaml |
| Time stop (code) | 90 天 / 涨幅<10% | _check_exits |
| 追踪 EMA 周期 | 20 | config.yaml |
| Trim gain threshold | 1.0（100%涨幅）| config.yaml |
| Extension 第 1 次减仓 | 20% | 默认 |
| Extension 第 1 次减仓 (Base n' Break) | 50% | 特殊规则 |

## 附录 B：关键文件路径速查

| 用途 | 路径 |
|------|------|
| 股票池（手动） | `UNIVERSE.md` |
| 股票池（指数缓存）| `data/index_cache.json` |
| 股票池（自动缓存）| `data/universe_cache.json` |
| K线数据缓存 | `data/cache/{SYMBOL}.pkl` |
| EPS 缓存 | `data/cache/eps_{SYMBOL}.pkl` |
| 配置 | `config.yaml` |
| 环境变量 | `.env` |
| 信号历史 | `output/v_oliver_kell/signals.csv` |
| 持仓 | `output/v_oliver_kell/positions.json` |
| 日报 | `output/v_oliver_kell/YYYY-MM-DD/报告_*.md` |
| 雷达 | `output/v_oliver_kell/YYYY-MM-DD/雷达_*.md` |
| 回测报告 | `output/v_oliver_kell/backtest/回测报告_*.md` |
| 信号汇总 | `output/SIGNALS_LOG.md` |
| 测试 | `tests/v_oliver_kell/test_*.py` |
| PRD | `docs/PRD_v_oliver_kell_2026-05-15_v2.md` |
| 策略原文 PDF | `Oliver_Kell_Victory_in_Stock_Trading.pdf` |

## 附录 C：故障排查

| 症状 | 原因 | 解决 |
|------|------|------|
| "未配置 Alpaca API Key" | `.env` 未填或路径错 | 检查 `.env` 在项目根目录 |
| "本地数据不足" | `data/cache/` 为空 | 首次运行会自动下载；耐心等待 |
| "Yahoo 403" | 限流 | 已自动 fallback 到 Alpaca |
| "Pandas FutureWarning" | 版本不匹配 | 固定 `pandas>=3.0.1` |
| "No module named 'akshare'" | 可选依赖缺失 | 不影响美股；港股/A 股才需要 |
| 回测 Sharpe 突然为 0 | 净值曲线无波动 | 检查所有股票价格数据是否完整 |
| 持仓文件被清空 | 手动运行了 clear_cache | 重新买入后保存 |

---

*本文档基于 2026-06-22 当前代码状态生成。如代码演进，请同步更新本文档。*
*生成者：Claude Code（信号系统项目调研总结）*
