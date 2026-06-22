"""
backtest/engine.py — 回测引擎

职责：
  1. 以指定的时间段和股票池逐日运行 SEPA 策略
  2. 追踪每笔交易（买入日期/价格 → 出场日期/价格）
  3. 构建每日净值曲线
  4. 计算胜率、盈亏比、最大回撤、年化收益、夏普比率
  5. 生成格式化回测报告

设计原则：
  - 引擎不修改策略代码，只观察策略产生的信号
  - 买入信号 → 记录一笔新交易
  - 卖出信号 → 关闭对应交易，记录盈亏
  - 回测结束时仍未平仓的头寸，以最后一天收盘价强制平仓
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from data.fetcher import fetch
from events import EventQueue
from strategies.base import StrategyBase


# ────────────────────────────────────────────────────────────────
# 数据结构
# ────────────────────────────────────────────────────────────────

@dataclass
class Trade:
    """
    记录一笔完整的交易（从买入到出场）。
    买入时创建，出场时调用 close() 填充出场信息。
    支持部分平仓：分级止盈中途卖出一部分时，用 partial_close() 结算已卖份额。
    """
    symbol: str
    entry_date: datetime
    entry_price: float
    shares: float = 0.0  # 持仓股数（支持部分平仓）
    exit_date: datetime | None = None
    exit_price: float | None = None
    exit_reason: str = ""
    pnl_pct: float = 0.0        # 盈亏百分比，正数=盈利，负数=亏损
    signal_strength: int = 0    # 入场时的信号强度
    entry_reason: str = ""       # 入场原因（策略详细指标）
    position_dollar: float = 0.0  # 入场金额（美元），0=使用引擎默认值
    add_on_triggered: bool = False  # 金字塔加仓是否已触发（用于回测统计）

    @property
    def is_closed(self) -> bool:
        return self.exit_date is not None

    def close(self, exit_date: datetime, exit_price: float, reason: str) -> None:
        self.exit_date = exit_date
        self.exit_price = exit_price
        self.exit_reason = reason
        self.pnl_pct = exit_price / self.entry_price - 1

    def partial_close(self, exit_date: datetime, exit_price: float, shares_sold: float, reason: str) -> "Trade":
        """
        部分平仓：结算已卖出份额的盈亏，返回一个已关闭的 Trade 代表该批次持仓。
        原 Trade 减少 shares 后继续追踪。
        """
        closed_trade = Trade(
            symbol=self.symbol,
            entry_date=self.entry_date,
            entry_price=self.entry_price,
            shares=shares_sold,
            exit_date=exit_date,
            exit_price=exit_price,
            exit_reason=reason,
            pnl_pct=exit_price / self.entry_price - 1,
            signal_strength=self.signal_strength,
            entry_reason=self.entry_reason,
            position_dollar=self.position_dollar,
            add_on_triggered=self.add_on_triggered,
        )
        # 剩余持仓继续追踪（shares 减少，entry_price 不变）
        self.shares -= shares_sold
        return closed_trade


@dataclass
class BacktestResult:
    """
    回测结果容器。包含所有交易记录和汇总指标。
    调用 print_report() 打印格式化报告。
    """
    start_date: datetime
    end_date: datetime
    symbols: list[str]
    trades: list[Trade]

    # 汇总指标
    total_trades: int
    win_rate: float             # 0.0 ~ 1.0
    profit_loss_ratio: float    # 平均盈利 / 平均亏损（绝对值）
    max_drawdown: float         # 0.0 ~ 1.0（正数代表亏损幅度）
    annualized_return: float    # 年化收益率，0.20 = 20%
    sharpe_ratio: float         # 夏普比率
    signals_per_month: float    # 平均每月买入信号数

    # 净值曲线（每日）
    equity_curve: pd.Series

    # 资金使用指标（仅固定金额模式）
    max_positions: int = 0       # 峰值持仓股数
    avg_positions: float = 0.0    # 平均持仓股数
    capital_usage_pct: float = 0.0  # 峰值资金使用比率（%）


    def print_report(self, label: str = "", strategy_name: str = "SEPA Minervini") -> None:
        """按 STRATEGY_PROTOCOL.md 规定的格式打印回测报告。"""
        sep = "═" * 51
        win_pass   = "✓" if self.win_rate >= 0.40 else "✗"
        plr_pass   = "✓" if self.profit_loss_ratio >= 1.5 else "✗"
        mdd_pass   = "✓" if self.max_drawdown <= 0.25 else "✗"
        freq_pass  = "✓" if 2 <= self.signals_per_month <= 10 else "✗"
        ar_pass    = "✓" if self.annualized_return >= 0.15 else "✓" if self.annualized_return > 0 else "✗"
        sr_pass    = "✓" if self.sharpe_ratio >= 1.0 else "✗"

        # 及格数量
        passes = sum([
            self.win_rate >= 0.40,
            self.profit_loss_ratio >= 1.5,
            self.max_drawdown <= 0.25,
            2 <= self.signals_per_month <= 10,
            self.annualized_return >= 0.15,
            self.sharpe_ratio >= 1.0,
        ])

        title = f"回测报告 — {strategy_name}{' (' + label + ')' if label else ''}"
        start_str = self.start_date.strftime("%Y-%m-%d")
        end_str = self.end_date.strftime("%Y-%m-%d")

        print(f"\n{sep}")
        print(f"  {title}")
        print(f"  测试区间：{start_str} 至 {end_str}")
        print(f"  股票池：{', '.join(self.symbols)}")
        print(sep)

        if self.total_trades == 0:
            print("  ⚠️  本区间内无完整交易记录。")
            print("     可能原因：数据不足 / 股票池太小 / 区间太短")
            print(sep)
            return

        print(f"  总交易笔数：{self.total_trades} 笔")
        # 实际金额（固定金额模式可通过初始净值 > 1 来判断）
        if len(self.equity_curve) >= 2 and float(self.equity_curve.iloc[0]) > 1:
            init_eq = float(self.equity_curve.iloc[0])
            final_eq = float(self.equity_curve.iloc[-1])
            dollar_ret = final_eq - init_eq
            pct_ret = dollar_ret / init_eq * 100
            sign = "+" if dollar_ret >= 0 else ""
            print(f"  初始本金：${init_eq:,.0f}  →  最终净值：${final_eq:,.0f}  实际收益：{sign}${dollar_ret:,.0f} ({pct_ret:+.1f}%)")
        print(f"  {'指标':<18} {'数值':>10}   {'及格线':>10}  {'状态'}")
        print(f"  {'-'*48}")
        print(f"  {'胜率':<18} {self.win_rate*100:>9.1f}%   {'> 40%':>10}   {win_pass}")
        print(f"  {'盈亏比':<17} {self.profit_loss_ratio:>10.2f}   {'> 1.5':>10}   {plr_pass}")
        print(f"  {'最大回撤':<16} {self.max_drawdown*100:>9.1f}%   {'< 25%':>10}   {mdd_pass}")
        print(f"  {'每月信号数':<15} {self.signals_per_month:>10.1f}   {'2 ~ 10':>10}   {freq_pass}")
        print(f"  {'年化收益':<16} {self.annualized_return*100:>9.1f}%   {'> 15%':>10}   {ar_pass}")
        print(f"  {'夏普比率':<16} {self.sharpe_ratio:>10.2f}   {'> 1.0':>10}   {sr_pass}")
        if self.max_positions > 0:
            print(f"  {'峰值持仓':<16} {self.max_positions:>10} 股")
            print(f"  {'平均持仓':<15} {self.avg_positions:>10.1f} 股")
            print(f"  {'资金使用峰值':<13} {self.capital_usage_pct:>9.1f}%")
        print(f"  {'-'*48}")
        print(f"  综合评级：{passes}/6 项达标")
        print()

        # 交易详情
        closed = [t for t in self.trades if t.is_closed]
        if closed:
            wins  = [t for t in closed if t.pnl_pct > 0]
            losses = [t for t in closed if t.pnl_pct <= 0]
            print(f"  【交易详情】")
            print(f"  盈利笔数：{len(wins)} 笔，平均盈利 "
                  f"{np.mean([t.pnl_pct for t in wins])*100:.1f}%" if wins else
                  f"  盈利笔数：0 笔")
            if losses:
                print(f"  亏损笔数：{len(losses)} 笔，平均亏损 "
                      f"{np.mean([t.pnl_pct for t in losses])*100:.1f}%")
            print()

            # 最近5笔交易
            recent = sorted(closed, key=lambda t: t.exit_date)[-5:]
            print(f"  【最近 {len(recent)} 笔交易记录】")
            print(f"  {'股票':<6} {'买入日':<12} {'卖出日':<12} {'买入价':>8} {'卖出价':>8} {'盈亏':>8}")
            for t in recent:
                sign = "+" if t.pnl_pct >= 0 else ""
                print(f"  {t.symbol:<6} "
                      f"{t.entry_date.strftime('%Y-%m-%d'):<12} "
                      f"{t.exit_date.strftime('%Y-%m-%d'):<12} "
                      f"${t.entry_price:>7.2f} "
                      f"${t.exit_price:>7.2f} "
                      f"{sign}{t.pnl_pct*100:>6.1f}%")

        print(sep)

        # 结论
        if passes >= 5:
            verdict = "合格 ✓ — 策略表现良好，可以继续使用"
        elif passes >= 3:
            verdict = "需要优化 — 部分指标未达标，见下方建议"
        else:
            verdict = "不合格 ✗ — 建议调整参数或重新审视策略"

        print(f"\n  【结论】{verdict}")
        if self.win_rate < 0.40:
            print("  • 胜率偏低：可以考虑提高 RS 排名门槛或增加持仓时长")
        if self.profit_loss_ratio < 1.5:
            print("  • 盈亏比不足：止损可能太紧，或止盈退出太早")
        if self.max_drawdown > 0.25:
            print("  • 回撤过大：建议加强市场整体趋势过滤（如 SPY 在 200 日均线之上才买入）")
        if self.signals_per_month < 2:
            print("  • 信号太少：股票池较小或条件过于严格；可扩大股票池")
        if self.signals_per_month > 10:
            print("  • 信号过多：可提高成交量倍数或 RS 排名门槛")
        print(sep)

    def save_report(
        self,
        path: Path,
        label: str = "",
        strategy_name: str = "SEPA Minervini",
    ) -> None:
        """将回测报告保存为 Markdown 文件。"""
        start_str = self.start_date.strftime("%Y-%m-%d")
        end_str   = self.end_date.strftime("%Y-%m-%d")
        now_str   = datetime.now().strftime("%Y-%m-%d %H:%M")
        title     = f"{strategy_name} 回测报告{' — ' + label if label else ''}"

        win_pass  = "✓" if self.win_rate >= 0.40 else "✗"
        plr_pass  = "✓" if self.profit_loss_ratio >= 1.5 else "✗"
        mdd_pass  = "✓" if self.max_drawdown <= 0.25 else "✗"
        freq_pass = "✓" if 2 <= self.signals_per_month <= 10 else "✗"
        ar_pass   = "✓" if self.annualized_return >= 0.15 else "✗"
        sr_pass   = "✓" if self.sharpe_ratio >= 1.0 else "✗"
        passes    = sum([
            self.win_rate >= 0.40,
            self.profit_loss_ratio >= 1.5,
            self.max_drawdown <= 0.25,
            2 <= self.signals_per_month <= 10,
            self.annualized_return >= 0.15,
            self.sharpe_ratio >= 1.0,
        ])

        if passes >= 5:
            verdict = "**合格 ✓** — 策略表现良好，可以继续使用"
        elif passes >= 3:
            verdict = "**需要优化** — 部分指标未达标，见下方建议"
        else:
            verdict = "**不合格 ✗** — 建议调整参数或重新审视策略"

        lines = [
            f"# {title}",
            "",
            f"> 测试区间：{start_str} 至 {end_str}  ",
            f"> 生成时间：{now_str}  ",
            f"> 股票池：共 {len(self.symbols)} 只",
            "",
            "---",
            "",
            "## 绩效指标",
            "",
            "| 指标 | 数值 | 及格线 | 状态 |",
            "|------|------|--------|------|",
            f"| 胜率 | {self.win_rate*100:.1f}% | > 40% | {win_pass} |",
            f"| 盈亏比 | {self.profit_loss_ratio:.2f} | > 1.5 | {plr_pass} |",
            f"| 最大回撤 | {self.max_drawdown*100:.1f}% | < 25% | {mdd_pass} |",
            f"| 每月信号数 | {self.signals_per_month:.1f} | 2 ~ 10 | {freq_pass} |",
            f"| 年化收益 | {self.annualized_return*100:.1f}% | > 15% | {ar_pass} |",
            f"| 夏普比率 | {self.sharpe_ratio:.2f} | > 1.0 | {sr_pass} |",
            "",
            f"**综合评级：{passes}/6 项达标**",
            "",
            "---",
            "",
        ]

        if self.total_trades == 0:
            lines += ["## 交易详情", "", "⚠️ 本区间内无完整交易记录。", ""]
        else:
            closed = [t for t in self.trades if t.is_closed]
            wins   = [t for t in closed if t.pnl_pct > 0]
            losses = [t for t in closed if t.pnl_pct <= 0]

            lines += [
                "## 交易详情",
                "",
                f"- 总交易笔数：{self.total_trades} 笔",
            ]
            if wins:
                lines.append(f"- 盈利笔数：{len(wins)} 笔，平均盈利 {np.mean([t.pnl_pct for t in wins])*100:.1f}%")
            if losses:
                lines.append(f"- 亏损笔数：{len(losses)} 笔，平均亏损 {np.mean([t.pnl_pct for t in losses])*100:.1f}%")

            if closed:
                recent = sorted(closed, key=lambda t: t.exit_date)[-10:]
                lines += [
                    "",
                    f"### 最近 {len(recent)} 笔交易",
                    "",
                    "| 股票 | 买入日 | 卖出日 | 买入价 | 卖出价 | 盈亏 |",
                    "|------|--------|--------|--------|--------|------|",
                ]
                for t in recent:
                    sign = "+" if t.pnl_pct >= 0 else ""
                    lines.append(
                        f"| {t.symbol} | {t.entry_date.strftime('%Y-%m-%d')} | "
                        f"{t.exit_date.strftime('%Y-%m-%d')} | "
                        f"${t.entry_price:.2f} | ${t.exit_price:.2f} | "
                        f"{sign}{t.pnl_pct*100:.1f}% |"
                    )
            lines.append("")
            lines.append("---")
            lines.append("")

        lines += ["## 结论", "", verdict, ""]

        suggestions = []
        if self.win_rate < 0.40:
            suggestions.append("- 胜率偏低：可以考虑提高 RS 排名门槛或增加持仓时长")
        if self.profit_loss_ratio < 1.5:
            suggestions.append("- 盈亏比不足：止损可能太紧，或止盈退出太早")
        if self.max_drawdown > 0.25:
            suggestions.append("- 回撤过大：建议加强市场整体趋势过滤（如 SPY 在 200 日均线之上才买入）")
        if self.signals_per_month < 2:
            suggestions.append("- 信号太少：股票池较小或条件过于严格；可扩大股票池")
        if self.signals_per_month > 10:
            suggestions.append("- 信号过多：可提高成交量倍数或 RS 排名门槛")
        if suggestions:
            lines += suggestions + [""]

        lines.append(f"*报告生成时间：{now_str}*")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")


# ────────────────────────────────────────────────────────────────
# 回测引擎
# ────────────────────────────────────────────────────────────────

class BacktestEngine:
    """
    事件驱动回测引擎。

    使用方式：
        engine = BacktestEngine(config, strategy_cls, strategy_config, symbols, start_date, end_date)
        result = engine.run()
        result.print_report(strategy_name=strategy_cls.strategy_name)
    """

    # SMA200 需要 200 天数据，再加 pivot_lookback(30) 天 = 约 280 天预热
    WARMUP_DAYS = 300

    def __init__(
        self,
        config: dict,
        strategy_cls: type,
        strategy_config: dict,
        symbols: list[str],
        start_date: datetime,
        end_date: datetime,
        save_signals_csv: bool = False,
        strategy_id: str = "",
        position_size: float | None = None,  # None = 等权重百分比模型，数值 = 固定金额（如 1000）
        initial_capital: float = 10_000.0,   # 初始本金（固定金额模型用）
    ) -> None:
        self.config = config
        self.strategy_cls = strategy_cls
        self.strategy_config = strategy_config
        self.symbols = symbols
        self.start_date = _ensure_utc(start_date)
        self.end_date = _ensure_utc(end_date)
        self.save_signals_csv = save_signals_csv
        self.strategy_id = strategy_id
        self.position_size = position_size
        self.initial_capital = initial_capital

    def run(self, verbose: bool = True) -> BacktestResult:
        """
        执行回测。

        参数：
            verbose: 是否打印进度（默认开）

        返回：
            BacktestResult，含所有交易记录和指标
        """
        total_days = (self.end_date - self.start_date).days + self.WARMUP_DAYS
        if verbose:
            print(f"  下载历史数据（{total_days} 天）...")

        market_data = fetch(self.symbols, history_days=total_days, end_date=self.end_date)
        if not market_data:
            raise RuntimeError("无法获取任何股票数据，回测中止。")

        # 确保基准 ETF 在 market_data 中（用于分市场 RS 计算）
        for benchmark, syms in [("SPY", ["SPY"]), ("ASHR", ["ASHR"]), ("EWT", ["EWT"])]:
            if benchmark not in market_data:
                data = fetch(syms, history_days=total_days, end_date=self.end_date)
                if data and benchmark in data:
                    market_data[benchmark] = data[benchmark]

        # 确定测试区间内的所有交易日
        # 优先使用 US 股票的数据（不会有 US holiday 数据缺口）
        # 如果没有 US 股票，再用第一个股票的数据
        ref_index = None
        us_symbols = {"SPY", "QQQ", "AAPL", "MSFT", "GOOG", "GOOGL", "AMZN", "NVDA",
                       "META", "TSLA", "AMD", "INTC", "CRM"}
        for sym in us_symbols:
            if sym in market_data:
                ref_index = market_data[sym].index
                break
        if ref_index is None:
            ref_df = next(iter(market_data.values()))
            ref_index = ref_df.index
        if ref_index.tzinfo is None:
            ref_index = ref_index.tz_localize("UTC")

        trading_days = ref_index[
            (ref_index >= self.start_date) & (ref_index <= self.end_date)
        ]

        if len(trading_days) == 0:
            raise RuntimeError(
                f"指定的日期范围 {self.start_date.date()} ~ {self.end_date.date()} "
                "内没有可用的交易日数据。"
            )

        if verbose:
            print(f"  回测区间共 {len(trading_days)} 个交易日，开始逐日运行...")

        # 初始化策略和事件队列
        # v_trend_collection 需要所有趋势策略实例
        if getattr(self.strategy_cls, "strategy_id", None) == "v_trend_collection":
            from strategies.registry import STRATEGY_REGISTRY
            all_strategies = []
            for sid, cls in STRATEGY_REGISTRY.items():
                if sid not in ("v_adx50", "v_trend_collection"):
                    all_strategies.append(cls(self.strategy_config, market_data))
            strategy = self.strategy_cls(
                self.strategy_config, market_data, all_strategies=all_strategies
            )
        else:
            strategy = self.strategy_cls(self.strategy_config, market_data)
        queue = EventQueue()

        # 确保策略的 index_symbol (如 QQQ) 在 market_data 中
        index_symbol = self.strategy_config.get("index_symbol", "QQQ")
        if index_symbol not in market_data:
            idx_data = fetch([index_symbol], history_days=total_days, end_date=self.end_date)
            if index_symbol in idx_data:
                market_data[index_symbol] = idx_data[index_symbol]

        # 追踪所有交易
        open_trades: dict[str, list[Trade]] = {}   # symbol → 正在持有的交易列表（支持同股票多仓位）
        all_trades: list[Trade] = []              # 全部交易（含已平仓和未平仓）

        for i, date in enumerate(trading_days):
            dt = date.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            signals = strategy.run_date(dt, queue)

            for sig in signals:
                symbol = sig.symbol
                direction = sig.data.get("direction", "")
                reason = sig.data.get("reason", "")
                strength = sig.data.get("strength", 0)

                if direction == "buy":
                    entry_price = _get_close(market_data, symbol, dt, strategy)
                    if entry_price is None:
                        continue
                    position_dollar = sig.data.get("position_dollar", self.position_size)
                    shares = position_dollar / entry_price if entry_price > 0 else 0.0
                    sig_shares = sig.data.get("shares", 0.0)
                    if sig_shares > 0:
                        shares = sig_shares  # 信号指定了精确股数

                    # 每个买入信号都创建新的独立交易
                    # （不再检查是否已有持仓，同一股票可同时持有多笔独立交易）
                    trade = Trade(
                        symbol=symbol,
                        entry_date=dt,
                        entry_price=entry_price,
                        shares=shares,
                        signal_strength=strength,
                        entry_reason=reason,
                        position_dollar=position_dollar,
                    )
                    if symbol not in open_trades:
                        open_trades[symbol] = []
                    open_trades[symbol].append(trade)
                    all_trades.append(trade)

                    # 同步股数到策略的 positions dict
                    if hasattr(strategy, 'positions') and symbol in strategy.positions:
                        strategy.positions[symbol].shares = shares

                    # 补档模式：同时把买入信号追加到 signals.csv
                    if self.save_signals_csv and self.strategy_id:
                        from signals.generator import _append_to_csv
                        stop_loss = sig.data.get("stop_loss")
                        stop_str = f"${stop_loss:.2f}" if stop_loss is not None else "—"
                        _append_to_csv([{
                            "日期": dt.strftime("%Y-%m-%d"),
                            "股票": symbol,
                            "信号": "买入",
                            "强度(1-5)": strength,
                            "触发原因": reason,
                            "参考止损": stop_str,
                        }], self.strategy_id)

                elif direction == "sell":
                    # 卖出信号：关闭对应股票的所有未平仓交易
                    if symbol not in open_trades or len(open_trades[symbol]) == 0:
                        continue
                    exit_price = _get_close(market_data, symbol, dt, strategy)
                    if exit_price is None:
                        continue
                    sig_shares = sig.data.get("shares", 0.0)

                    # 卖出所有未平仓交易
                    trades_to_close = open_trades.get(symbol, [])
                    for trade in trades_to_close:
                        if sig_shares > 0 and trade.shares > 0:
                            # 部分平仓
                            if sig_shares < trade.shares:
                                closed_trade = trade.partial_close(dt, exit_price, sig_shares, reason)
                                all_trades.append(closed_trade)
                            else:
                                # 全部卖出
                                trade.close(dt, exit_price, reason)
                        else:
                            trade.close(dt, exit_price, reason)
                    # 清空该股票的所有持仓
                    open_trades[symbol] = []
                    if hasattr(strategy, 'positions') and symbol in strategy.positions:
                        del strategy.positions[symbol]

            # 进度提示（每 50 天打印一次）
            if verbose and (i + 1) % 50 == 0:
                pct = (i + 1) / len(trading_days) * 100
                print(f"    进度：{i+1}/{len(trading_days)} 天 ({pct:.0f}%)")

        # 将测试结束时仍未平仓的头寸强制平仓（以最后一日收盘价）
        for symbol, trades in list(open_trades.items()):
            exit_price = _get_close(market_data, symbol, self.end_date, strategy)
            if exit_price is not None:
                for trade in trades:
                    if not trade.is_closed:
                        trade.close(self.end_date, exit_price, "回测结束强制平仓")

        # 清空队列（不需要额外处理）
        while not queue.empty():
            queue.get()

        # 构建净值曲线
        closed_trades = [t for t in all_trades if t.is_closed]
        if verbose:
            print(f"  共产生 {len(all_trades)} 笔交易，构建净值曲线...")

        equity_curve, max_pos, avg_pos, cap_usage = self._build_equity_curve(
            closed_trades, market_data, trading_days
        )

        # 计算汇总指标
        metrics = self._calculate_metrics(closed_trades, equity_curve)

        return BacktestResult(
            start_date=self.start_date,
            end_date=self.end_date,
            symbols=self.symbols,
            trades=all_trades,
            equity_curve=equity_curve,
            max_positions=max_pos,
            avg_positions=avg_pos,
            capital_usage_pct=cap_usage,
            **metrics,
        )

    def _build_equity_curve(
        self,
        closed_trades: list[Trade],
        market_data: dict,
        trading_days: pd.DatetimeIndex,
    ) -> tuple[pd.Series, int, float, float]:
        """
        逐日计算组合净值。

        返回：(equity_series, max_positions, avg_positions, capital_usage_pct)
        固定金额模式返回持仓统计数据；等权重百分比模式后三个值为 0。

        两种模型：
          - position_size = None（默认）：等权重百分比模型，净值从 1.0 累乘
          - position_size = 数值（如 1000）：固定金额模型，初始本金 initial_capital
        """
        # 预处理：确保 market_data 的 index 都有时区信息
        sliced_data: dict[str, pd.DataFrame] = {}
        for sym, df in market_data.items():
            idx = df.index
            if idx.tzinfo is None:
                df = df.copy()
                df.index = idx.tz_localize("UTC")
            sliced_data[sym] = df

        equity = pd.Series(
            index=pd.DatetimeIndex(trading_days),
            dtype=float,
        )

        # ── 固定金额模型 ────────────────────────────────────────────
        if self.position_size is not None:
            cash = float(self.initial_capital)
            active_positions: dict[str, dict] = {}  # symbol -> {shares, cost}
            sorted_trades = sorted(closed_trades, key=lambda t: _ensure_utc(t.entry_date))
            daily_position_counts: list[int] = []

            for i, date in enumerate(trading_days):
                dt = date.to_pydatetime()
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                dt_date = dt.date()

                # ── 当日卖出：资金回 cash ──────────────────────────────
                for t in closed_trades:
                    exit_dt = _ensure_utc(t.exit_date) if t.exit_date else None
                    if exit_dt and exit_dt.date() == dt_date and t.symbol in active_positions:
                        pos = active_positions[t.symbol]
                        pnl = (t.exit_price - t.entry_price) * pos['shares']
                        cash += pos['position_dollar'] + pnl
                        del active_positions[t.symbol]

                # ── 新买入：现金不足时先卖持仓 ─────────────────────────
                trade_idx = 0
                while trade_idx < len(sorted_trades):
                    t = sorted_trades[trade_idx]
                    entry_date = _ensure_utc(t.entry_date).date()
                    if entry_date < dt_date:
                        trade_idx += 1
                        continue
                    if entry_date == dt_date and t.symbol not in active_positions:
                        needed = t.position_dollar if t.position_dollar > 0 else self.position_size
                        # 现金不够时，卖出收益最低+持仓最久的
                        while cash < needed and active_positions:
                            # 计算每只持仓的当前收益%（当日收盘价）
                            perf = []
                            for sym, pos in active_positions.items():
                                df = sliced_data.get(sym)
                                cur_price = pos['entry_price']  # 默认用入场价
                                if df is not None:
                                    mask = df.index <= dt
                                    if mask.sum() >= 1:
                                        cur_price = float(df["close"][mask].iloc[-1])
                                ret_pct = (cur_price - pos['entry_price']) / pos['entry_price']
                                days_held = (dt_date - _ensure_utc(t.entry_date).date()).days if 'entry_date' in pos else 0
                                perf.append((sym, ret_pct, days_held))
                            # 排序：收益最低优先，收益相同则持仓最久优先
                            perf.sort(key=lambda x: (x[1], x[2]))
                            sym_to_sell = perf[0][0]
                            pos = active_positions[sym_to_sell]
                            df = sliced_data.get(sym_to_sell)
                            cur_price = pos['entry_price']
                            if df is not None:
                                mask = df.index <= dt
                                if mask.sum() >= 1:
                                    cur_price = float(df["close"][mask].iloc[-1])
                            sell_value = cur_price * pos['shares']
                            cash += sell_value
                            del active_positions[sym_to_sell]
                        # 现金足够后再买入
                        if cash >= needed:
                            shares = needed / t.entry_price
                            active_positions[t.symbol] = {
                                'shares': shares,
                                'cost': needed,
                                'entry_price': t.entry_price,
                                'entry_date': _ensure_utc(t.entry_date).date(),
                                'position_dollar': needed,
                            }
                            cash -= needed
                    # Move to next trade regardless of whether we bought or not
                    trade_idx += 1
                    # Continue processing trades for today (entry_date == dt_date)
                    # but stop when we hit future entries (entry_date > dt_date)
                    if trade_idx < len(sorted_trades):
                        next_entry_date = _ensure_utc(sorted_trades[trade_idx].entry_date).date()
                        if next_entry_date > dt_date:
                            break

                # 计算持仓市值
                # 使用日历日期匹配（不用 timestamp 比较），因为不同时区的股票时间戳不同
                pos_value = 0.0
                for sym, pos in active_positions.items():
                    df = sliced_data.get(sym)
                    if df is not None:
                        # 用当前交易日（dt_date）的日历日期匹配当日收盘价
                        # df.index 是 UTC timestamps，提取日期进行比较
                        df_dates = pd.Series([d.date() for d in df.index], index=df.index)
                        df_today = df[df_dates == dt_date]
                        if not df_today.empty:
                            # 当日有数据，用当日收盘价
                            cur_price = float(df_today["close"].iloc[-1])
                            pos_value += cur_price * pos['shares']
                        else:
                            # 如果当天没有数据（e.g., 周末/节假日），用最近的一个收盘价
                            cur_price = float(df["close"].iloc[-1])
                            pos_value += cur_price * pos['shares']

                equity.iloc[i] = cash + pos_value
                daily_position_counts.append(len(active_positions))

            # 统计持仓数据
            max_positions = max(daily_position_counts) if daily_position_counts else 0
            avg_positions = float(np.mean(daily_position_counts)) if daily_position_counts else 0.0
            peak_used = max_positions * self.position_size
            capital_usage_pct = round(peak_used / self.initial_capital * 100, 1) if self.initial_capital > 0 else 0.0

            return equity, max_positions, avg_positions, capital_usage_pct

        # ── 等权重百分比模型（默认）────────────────────────────────
        portfolio_value = 1.0

        for i, date in enumerate(trading_days):
            dt = date.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # 找当日活跃的持仓
            active_symbols = []
            for trade in closed_trades:
                entry = _ensure_utc(trade.entry_date)
                exit_ = _ensure_utc(trade.exit_date)
                if entry <= dt <= exit_:
                    active_symbols.append(trade.symbol)

            if not active_symbols or i == 0:
                equity.iloc[i] = portfolio_value
                continue

            # 计算每个持仓今日的日收益率
            daily_returns = []
            for sym in active_symbols:
                df = sliced_data.get(sym)
                if df is None:
                    continue
                mask = df.index <= dt
                if mask.sum() < 2:
                    continue
                today_close = float(df["close"][mask].iloc[-1])
                prev_close = float(df["close"][mask].iloc[-2])
                if prev_close > 0:
                    daily_returns.append(today_close / prev_close - 1)

            if daily_returns:
                portfolio_value *= (1 + float(np.mean(daily_returns)))

            equity.iloc[i] = portfolio_value

        return equity, 0, 0.0, 0.0

        # ── 等权重百分比模型（默认）────────────────────────────────
        portfolio_value = 1.0

        for i, date in enumerate(trading_days):
            dt = date.to_pydatetime()
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            # 找当日活跃的持仓
            active_symbols = []
            for trade in closed_trades:
                entry = _ensure_utc(trade.entry_date)
                exit_ = _ensure_utc(trade.exit_date)
                if entry <= dt <= exit_:
                    active_symbols.append(trade.symbol)

            if not active_symbols or i == 0:
                equity.iloc[i] = portfolio_value
                continue

            # 计算每个持仓今日的日收益率
            daily_returns = []
            for sym in active_symbols:
                df = sliced_data.get(sym)
                if df is None:
                    continue
                mask = df.index <= dt
                if mask.sum() < 2:
                    continue
                today_close = float(df["close"][mask].iloc[-1])
                prev_close = float(df["close"][mask].iloc[-2])
                if prev_close > 0:
                    daily_returns.append(today_close / prev_close - 1)

            if daily_returns:
                portfolio_value *= (1 + float(np.mean(daily_returns)))

            equity.iloc[i] = portfolio_value

        return equity

    # ────────────────────────────────────────────────────────────
    # 指标计算
    # ────────────────────────────────────────────────────────────

    def _calculate_metrics(
        self, closed_trades: list[Trade], equity_curve: pd.Series
    ) -> dict:
        total_trades = len(closed_trades)

        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "profit_loss_ratio": 0.0,
                "max_drawdown": 0.0,
                "annualized_return": 0.0,
                "sharpe_ratio": 0.0,
                "signals_per_month": 0.0,
            }

        wins = [t for t in closed_trades if t.pnl_pct > 0]
        losses = [t for t in closed_trades if t.pnl_pct <= 0]

        # 胜率
        win_rate = len(wins) / total_trades

        # 盈亏比：平均盈利 / 平均亏损（绝对值）
        avg_win = float(np.mean([t.pnl_pct for t in wins])) if wins else 0.0
        avg_loss = float(abs(np.mean([t.pnl_pct for t in losses]))) if losses else 1e-6
        profit_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0

        # 最大回撤
        max_drawdown = self._calc_max_drawdown(equity_curve)

        # 年化收益（用净值曲线首尾计算）
        days_in_range = (self.end_date - self.start_date).days
        years = days_in_range / 365.25
        if years > 0 and len(equity_curve) >= 2:
            total_return = float(equity_curve.iloc[-1] / equity_curve.iloc[0] - 1)
            annualized_return = float((1 + total_return) ** (1 / years) - 1)
        else:
            annualized_return = 0.0

        # 夏普比率（假设无风险利率 = 0）
        sharpe_ratio = self._calc_sharpe(equity_curve)

        # 每月信号数（以买入信号为准）
        total_months = days_in_range / 30.44
        signals_per_month = total_trades / total_months if total_months > 0 else 0.0

        return {
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_loss_ratio": profit_loss_ratio,
            "max_drawdown": max_drawdown,
            "annualized_return": annualized_return,
            "sharpe_ratio": sharpe_ratio,
            "signals_per_month": signals_per_month,
        }

    @staticmethod
    def _calc_max_drawdown(equity_curve: pd.Series) -> float:
        """从净值曲线计算最大回撤（0.20 代表最大从高点跌了 20%）。"""
        if equity_curve.empty:
            return 0.0
        rolling_max = equity_curve.cummax()
        drawdown = (equity_curve - rolling_max) / rolling_max
        return float(abs(drawdown.min()))

    @staticmethod
    def _calc_sharpe(equity_curve: pd.Series) -> float:
        """年化夏普比率（假设无风险利率 = 0）。"""
        if len(equity_curve) < 2:
            return 0.0
        daily_ret = equity_curve.pct_change().dropna()
        std = float(daily_ret.std())
        if std == 0:
            return 0.0
        return float(daily_ret.mean() / std * np.sqrt(252))


# ────────────────────────────────────────────────────────────────
# 辅助函数
# ────────────────────────────────────────────────────────────────

def _ensure_utc(dt: datetime | None) -> datetime | None:
    """确保 datetime 有时区信息（UTC）。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _get_close(
    market_data: dict,
    symbol: str,
    date: datetime,
    strategy: StrategyBase,
) -> float | None:
    """
    获取 symbol 在 date 当天的收盘价。

    yfinance 对美股返回每日两个 bar（05:00 和 14:30 UTC），
    其中 14:30 UTC 的 bar 代表当日收盘交易。
    而 05:00 UTC 的 bar 是前一日的盘后收盘。
    所以 iloc[-1] 可能返回次日 05:00 的错误价格。

    修复：找到与 date 日历日期匹配的最接近 bar。
    """
    df = market_data.get(symbol)
    if df is None:
        return None
    df_sliced = strategy._slice_to_date(df, date)
    if df_sliced.empty:
        return None

    # 找到与 date 的日历日期匹配的最后一行
    # date 可能是带时区的 UTC 时间，我们只比较日历日期
    if hasattr(date, 'tzinfo') and date.tzinfo is not None:
        date_normalized = date.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        date_normalized = date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

    # 在 sliced 数据中找到与 date 属于同一日历日的 bar
    # 即：bar 的日期（去掉时间）== date 的日历日期
    target_date = date_normalized.date()
    df_with_date = df_sliced.copy()
    df_with_date['_date_only'] = pd.Series([d.date() for d in df_with_date.index], index=df_with_date.index)
    df_matched = df_with_date[df_with_date['_date_only'] == target_date]
    if df_matched.empty:
        # 没有当天数据，返回 None 让调用方跳过这笔交易
        return None
    return float(df_matched["close"].iloc[-1])
