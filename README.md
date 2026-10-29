# Signal System Oliver

> 基于 Oliver Kell *Cycle of Price Action* 六阶段理论的事件驱动美股信号系统

每日收盘后自动扫描股票池，输出**买入 / 做空 / 出场 / 观望**四类信号，附带触发原因、参考止损、强度评级。

**系统不自动下单，所有信号仅供参考。**

---

## 项目亮点

| 维度 | 说明 |
|------|------|
| **策略** | Oliver Kell 六阶段循环：Reversal Extension → Wedge Pop → EMA Crossback → Base n' Break → Exhaustion → Wedge Drop |
| **架构** | 事件驱动，策略插件化（`StrategyBase` + `STRATEGY_REGISTRY`）|
| **数据** | 三层缓存（本地 → 增量 → 全量），Alpaca IEX 主源 + Yahoo 备用 + GitHub VIX |
| **回测** | 事件驱动回测引擎，支持样本内/外拆分，6 项指标评估（Sharpe、年化、回撤、胜率、盈亏比、信号频率）|
| **报告** | 每日 Markdown 日报 + 雷达报告（含 Watchlist 候选）|
| **自动化** | macOS launchd 每日北京时间 05:30 自动运行 + 系统通知 |

---

## 快速开始

### 环境要求

- Python 3.13+
- [uv](https://github.com/astral-sh/uv)（推荐）或 pip
- 至少 5GB 可用磁盘（数据缓存）

### 安装

```bash
git clone https://github.com/wubo1992/signal-system-oliver.git
cd signal-system-oliver
uv sync
```

### 配置 API Key

```bash
cp .env.example .env
# 编辑 .env，填入你的 Alpaca API Key
```

获取免费 API Key：[Alpaca Markets](https://alpaca.markets/)（注册即送 IEX 实时 + 历史数据）

> 可选：Finnhub（EPS）、Alpha Vantage（2010-2016 历史）、Polygon、SEC EDGAR（完全免费但慢）

### 第一次运行（下载 302 只美股约 10 年历史数据）

```bash
uv run python main.py --mode live --strategy v_oliver_kell
```

首次运行会下载约 7GB 历史数据（耗时 5-15 分钟）。之后每次增量更新只需 30 秒。

### 跑回测

```bash
uv run python main.py --mode backtest \
    --start 2026-01-01 --end 2026-05-13 \
    --strategy v_oliver_kell
```

报告自动保存到 `output/v_oliver_kell/backtest/`。

---

## 信号类型

| 方向 | 类型 | 强度 | 触发条件简述 |
|------|------|------|-------------|
| 🟢 买入 | Wedge Pop | ★★★★★ | EMA 下方盘整后放量突破（最佳买点）|
| 🟢 买入 | EMA Crossback | ★★★★☆ | 价格回踩 EMA 后次日确认上行 |
| 🟢 买入 | Base n' Break | ★★★☆☆ | EMA20 上方盘整 10-20 天后突破 |
| 🟢 买入 | Variant Patterns | ★★☆☆☆ | VCP / Bull Flag / Bull Pennant |
| 🔴 做空 | Wedge Drop Short | ★★★★★ | 价格 < EMA10 × 0.92，EMA 双降 |
| 🔴 做空 | Exhaustion Short | ★★★★☆ | 顶部衰竭 + Gap Up ≥ 3% |
| ⚪ 卖出 | Exit (7级优先级) | — | Wedge Drop / 硬止损 / EMA20 跌破 / 假突破 / 主动减仓 / 时间止损 / 3x Trapped |
| 👀 观望 | Reversal Extension | ★★★ | 价格远低于 EMA20 + 放量下跌（Capitulation）|
| 👀 观望 | Base Tightening | ★★ | EMA 上方 + 10 天波动率 < 5%（待突破）|

详细规则见 [`docs/PRD_v_oliver_kell_2026-05-15_v2.md`](docs/PRD_v_oliver_kell_2026-05-15_v2.md)。

---

## 相对强度指标

所有信号都带四列相对强度数据，控制台 / CSV / 日报 / 雷达报告一致：

| 列 | 含义 |
|----|------|
| `RS (10D)` | 过去 10 个交易日涨幅 ÷ SPY 同期涨幅（倍数，1.0 = 与大盘同步）|
| `RS (20D)` | 过去 20 个交易日涨幅 ÷ SPY 同期涨幅（倍数）|
| `RS (10W)` | 过去 50 个交易日涨幅 ÷ SPY 同期涨幅（倍数）|
| `RS评级` | O'Neil RS Rating：1~99 横截面百分位（全市场排名）|
| `RS倍数` | (1 + 个股 252 日涨幅) ÷ (1 + SPY 252 日涨幅)，财富指数之比，恒为正 |

**O'Neil RS Rating** 公式（社区复刻口径，IBD 官方从未公布）：

```
RS Raw = 0.4 × ROC(63) + 0.2 × ROC(126) + 0.2 × ROC(189) + 0.2 × ROC(252)
RS Rating = RS Raw 在横截面股票池内的百分位排名
```

ROC 用**绝对**涨幅、不除以大盘 —— RS Rating 是股票之间互比，跟标普比的是 RS Line。
横截面股票池 = 全市场普通股（约 5,500 只），剔除权证 / 优先股 / 债券与僵尸票（数据停滞 30 天以上），
保留 ETF 与 REIT。上市未满一年的新股按**可用窗口权重归一化**参与排名，不直接剔除。

实现见 [`strategies/v_oliver_kell/oneil_rs.py`](strategies/v_oliver_kell/oneil_rs.py)。

---

## 股票池

合并三个来源（去重排序）：

1. **手动池**：直接编辑 [`UNIVERSE.md`](UNIVERSE.md)（当前 302 只美股）
2. **指数成分股**：S&P 500 / Nasdaq 100 / Russell 2000（Wikipedia + 本地缓存）
3. **Alpaca 新闻自动池**：每日增量更新，超 365 天未提及自动移出

启用指数：

```yaml
# config.yaml
auto_universe:
  include_indices: ["sp500", "nasdaq100"]
```

---

## 项目结构

```
signal-system-oliver/
├── main.py                            # CLI 入口（live/backtest/scan）
├── config.yaml                        # 全局配置
├── pyproject.toml                     # Python 项目元数据
├── DEVELOPMENT_GUIDE.md               # ★ 详细开发文档（含架构、扩展、复现步骤）
│
├── data/                              # 数据层
│   ├── fetcher.py                     # 三层缓存 + Alpaca/Yahoo/VIX
│   ├── fundamentals.py                # EPS 数据
│   ├── balance_sheet.py               # 资产负债表 + NCAV
│   ├── sec_edgar.py                   # SEC XBRL
│   └── ...
│
├── universe/                          # 股票池
│   ├── manager.py                     # 合并手动+指数+自动
│   ├── index_fetcher.py               # 指数成分股
│   ├── alpaca_fetcher.py              # Alpaca 新闻
│   ├── sa_scanner.py                  # SA Quant 评分
│   └── updater.py                     # 写入 UNIVERSE.md
│
├── events/                            # 事件层
│   ├── base.py                        # Event/BarEvent/SignalEvent
│   └── queue.py                       # EventQueue
│
├── strategies/                        # 策略层（插件化）
│   ├── base.py                        # StrategyBase 抽象基类
│   ├── registry.py                    # STRATEGY_REGISTRY
│   └── v_oliver_kell/                 # ★ 当前在线策略
│       ├── oliver_kell_strategy.py    # 主类
│       ├── cycle_detector.py          # 六阶段识别
│       ├── wedge_finder.py            # 楔形检测
│       ├── market_environment.py      # QQQ 四档状态
│       ├── scale_in.py                # 分批建仓
│       ├── exit_manager.py            # 7 级出场
│       └── oneil_rs.py                # O'Neil RS 评级（横截面百分位）
│
├── signals/                           # 信号输出
│   ├── generator.py                   # 控制台 + CSV
│   ├── report.py                      # 每日 Markdown 报告
│   ├── oliver_kell_radar_report.py    # 雷达报告
│   ├── watchlist_scanner.py           # Watchlist 候选
│   └── positions.py                   # 持仓 JSON 持久化
│
├── backtest/                          # 回测引擎
│   └── engine.py                      # BacktestEngine
│
├── tests/v_oliver_kell/               # 单元测试
│
├── output/                            # 运行时输出（gitignored）
│
├── UNIVERSE.md                        # ★ 手动股票池（唯一来源）
├── Oliver_Kell_Victory_in_Stock_Trading.pdf  # 策略原文（gitignored，版权）
└── run_daily.sh                       # macOS 自动运行脚本
```

---

## 添加新策略

```python
# strategies/vN_xxx/my_strategy.py
from strategies.base import StrategyBase
from events import EventQueue, SignalEvent

class MyStrategy(StrategyBase):
    strategy_id = "vN_xxx"
    strategy_name = "我的策略"

    def __init__(self, cfg, market_data, live_mode=False):
        super().__init__(cfg, market_data)
        self.positions = {}

    def run_date(self, date, queue):
        signals = []
        for symbol, df in self.market_data.items():
            # ... 你的逻辑 ...
            # queue.put(SignalEvent.create(...))
        return signals
```

注册到 `strategies/registry.py`，在 `config.yaml` 添加配置段即可。详见 [`HOW_TO_ADD_STRATEGY.md`](HOW_TO_ADD_STRATEGY.md)。

---

## 市场环境过滤

系统根据 QQQ vs 20 EMA 关系自动调整仓位上限：

| 环境 | 条件 | 最大仓位 | 最多信号数 |
|------|------|---------|-----------|
| Quality | QQQ > EMA20 × 1.01 | 190% | 10 |
| Average | QQQ 在 EMA20 ±1% | 50% | 5 |
| Poor | QQQ < EMA20 × 0.99 | 30% | 2 |
| Hostile | 10 日内 8 天收跌 | 0% | 0 |

---

## 回测评估指标

| 指标 | 及格线 |
|------|--------|
| 胜率 | > 40% |
| 盈亏比 | > 1.5 |
| 最大回撤 | < 25% |
| 每月信号数 | 2 ~ 10 |
| 年化收益 | > 15% |
| 夏普比率 | > 1.0 |

≥ 5/6 项达标视为策略合格。

---

## 文档

- 📘 [**DEVELOPMENT_GUIDE.md**](DEVELOPMENT_GUIDE.md) — 完整开发文档（架构、复现、扩展、陷阱）
- 📋 [docs/PRD_v_oliver_kell_2026-05-15_v2.md](docs/PRD_v_oliver_kell_2026-05-15_v2.md) — 产品 PRD（详细规则）
- 📚 [docs/strategies/](docs/strategies/) — 历史策略文档
- 🛠 [HOW_TO_ADD_STRATEGY.md](HOW_TO_ADD_STRATEGY.md) — 新策略开发指南

---

## 致谢

- **Oliver Kell** —— 《Cycle of Price Action》理论作者
- **Alpaca** —— 免费美股市场数据
- **Finnhub** / **Alpha Vantage** / **Polygon** —— 财务数据
- **SEC EDGAR** —— 完全免费的 XBRL 财务数据

---

## 免责声明

本系统仅供学习和研究用途，所有输出均为技术信号，**不构成投资建议**。
历史回测结果不代表未来表现。使用者自行承担投资决策风险。

---

## 许可证

[MIT](LICENSE) © 2026 wubo
