"""
signals/oliver_kell_radar_report.py — Oliver Kell 每日雷达报告

7 模块分类：
    🟢 猎物出击 (Long Entries): [Wedge Pop], [EMA Crossback], [Base n' Break] direction=buy
    🔵 乘胜追击 (Scale In): [Batch 2]
    🟡 利润收割 (Active Trim): [Extension Sell] 涨幅 > 100%
    🔴 纪律防守 (Exits): [EMA20 Break], [Hard Stop 8%], [Ignite Bar Stop]
    🦅 趋势逆转 (Trend Reversal): [Wedge Drop], [Failed Breakout], [Time Stop], [3x Trapped]
    🦅 放空出击 (Short Entries): [Wedge Drop Short], [Exhaustion Short]
    🔭 前瞻观察池 (Watchlist): direction=watch OR [Reversal Extension], [Base Tightening]
"""

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── 路径 ───────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ══════════════════════════════════════════════════════════
# 公开接口
# ══════════════════════════════════════════════════════════

def parse_reason_tag(reason: str) -> str | None:
    """
    从 reason 字符串中提取 cycle stage tag。

    例如：
        '[Wedge Pop] Best entry | [EMA] 10=100.0, 20=95.0'
        → 'wedge_pop'
    """
    # 匹配方括号内的标签
    match = re.search(r"\[([A-Za-z0-9 ]+)\]", reason)
    if match:
        tag = match.group(1).strip()
        # 映射常见标签到 cycle_stage 格式
        tag_map = {
            "Wedge Pop": "wedge_pop",
            "EMA Crossback": "ema_crossback",
            "Base n' Break": "base_n_break",
            "Batch 2": "batch2",
            "Extension Sell": "extension_sell",
            "EMA20 Break": "ema20_break",
            "Hard Stop 8%": "hard_stop",
            "Ignite Bar Stop": "ignite_bar_stop",
            "Wedge Drop": "wedge_drop",
            "Failed Breakout": "failed_breakout",
            "Time Stop": "time_stop",
            "3x Trapped": "3x_trapped",
            "Reversal Extension": "reversal_extension",
            "Base Tightening": "base_tightening",
            "VCP": "vcp",
            "Bull Flag": "bull_flag",
            "Bull Pennant": "bull_pennant",
        }
        return tag_map.get(tag, tag.lower().replace(" ", "_"))
    return None


def _record_to_dict(r) -> dict:
    """把 SignalEvent 或 dict 统一转换为 dict 格式。"""
    if isinstance(r, dict):
        return r
    # SignalEvent 对象
    if hasattr(r, "data"):
        return {
            "股票": getattr(r, "symbol", ""),
            "信号": r.data.get("direction", ""),
            "触发原因": r.data.get("reason", ""),
            "cycle_stage": r.data.get("cycle_stage"),
            "current_price": r.data.get("current_price"),
            "强度(1-5)": r.data.get("strength", 0),
            "参考止损": r.data.get("stop_loss"),
            "日期": r.timestamp.strftime("%Y-%m-%d") if hasattr(r, "timestamp") else "",
        }
    return {}


def categorize_signals(records: list) -> dict[str, list[dict]]:
    """
    将信号记录分类到 6 个模块。

    参数：
        records: process_signals() 返回的信号列表（dict 或 SignalEvent）

    返回：
        dict，key 是模块名，value 是该模块的信号列表
    """
    modules = {
        "LONG_ENTRIES": [],      # 🟢 猎物出击
        "SCALE_IN": [],          # 🔵 乘胜追击
        "ACTIVE_TRIM": [],       # 🟡 利润收割
        "PASSIVE_EXIT": [],      # 🔴 纪律防守
        "TREND_REVERSAL": [],    # 🦅 趋势逆转
        "WATCHLIST": [],         # 🔭 前瞻观察池
        "SHORT_ENTRIES": [],     # 🦅 放空出击 (Short Entries)
    }

    for r in records:
        rec = _record_to_dict(r)
        direction = rec.get("信号", rec.get("direction", ""))
        reason = rec.get("触发原因", rec.get("reason", ""))
        cycle_stage = rec.get("cycle_stage", parse_reason_tag(reason))
        signal_type = rec.get("信号", "")

        # Watchlist / 观望方向
        if direction == "watch" or "Reversal Extension" in reason or "Base Tightening" in reason:
            modules["WATCHLIST"].append(rec)
            continue

        # ── 买入类信号 ─────────────────────────────
        if direction == "买入" or direction == "buy":
            # Batch 2 → Scale In
            if cycle_stage == "batch2" or "Batch 2" in reason:
                modules["SCALE_IN"].append(rec)
            # Extension Sell（涨幅 > 100%）→ Active Trim
            elif cycle_stage == "extension_sell" or "Extension Sell" in reason:
                # 从 reason 中提取涨幅
                gain_match = re.search(r'\+\-?[\d.]+%', reason)
                if gain_match and "%" in reason:
                    gain_str = gain_match.group().replace("%", "").replace("+", "")
                    try:
                        gain = float(gain_str)
                        if gain > 100:
                            modules["ACTIVE_TRIM"].append(rec)
                        else:
                            modules["PASSIVE_EXIT"].append(rec)
                    except ValueError:
                        modules["PASSIVE_EXIT"].append(rec)
                else:
                    modules["PASSIVE_EXIT"].append(rec)
            # Long Entry 信号
            elif cycle_stage in ("wedge_pop", "ema_crossback", "base_n_break", "vcp", "bull_flag", "bull_pennant"):
                modules["LONG_ENTRIES"].append(rec)
            # 未知买入
            else:
                modules["LONG_ENTRIES"].append(rec)

        # ── 卖出类信号 ─────────────────────────────
        elif direction == "卖出" or direction == "sell":
            # Trend Reversal
            if cycle_stage in ("wedge_drop", "failed_breakout", "time_stop", "3x_trapped"):
                modules["TREND_REVERSAL"].append(rec)
            # Passive Exit（EMA20 Break, Hard Stop, Ignite Bar Stop）
            elif cycle_stage in ("ema20_break", "hard_stop", "ignite_bar_stop"):
                modules["PASSIVE_EXIT"].append(rec)
            # Extension Sell → Active Trim（涨幅 > 100%）或 Passive Exit
            elif cycle_stage == "extension_sell" or "Extension Sell" in reason:
                gain_match = re.search(r'\+\-?[\d.]+%', reason)
                if gain_match and "%" in reason:
                    gain_str = gain_match.group().replace("%", "").replace("+", "")
                    try:
                        gain = float(gain_str)
                        if gain > 100:
                            modules["ACTIVE_TRIM"].append(rec)
                        else:
                            modules["PASSIVE_EXIT"].append(rec)
                    except ValueError:
                        modules["PASSIVE_EXIT"].append(rec)
                else:
                    modules["PASSIVE_EXIT"].append(rec)
            # 未知卖出 → Passive Exit
            else:
                modules["PASSIVE_EXIT"].append(rec)

        # ── 做空类信号 ─────────────────────────────
        elif direction == "做空" or direction == "short":
            # Short entries: Wedge Drop Short, Exhaustion Short
            if cycle_stage in ("wedge_drop_short", "exhaustion_short", "wedge_drop", "exhaustion_extension"):
                modules["SHORT_ENTRIES"].append(rec)
            else:
                modules["SHORT_ENTRIES"].append(rec)

    return modules


def generate_radar_report(
    today_records: list[dict],
    watchlist_records: list[dict],
    strategy_id: str,
    strategy_name: str,
) -> Path:
    """
    生成 6 模块雷达报告，保存到 output/{strategy_id}/YYYY-MM-DD/雷达_{strategy_name}_YYYY-MM-DD.md

    参数：
        today_records: 今天新产生的信号
        watchlist_records: watchlist 扫描结果
        strategy_id: 策略文件夹 ID
        strategy_name: 策略显示名称

    返回：
        报告文件的 Path
    """
    today = datetime.now(tz=timezone.utc)
    today_str = today.strftime("%Y-%m-%d")

    # 创建输出目录
    day_dir = OUTPUT_DIR / strategy_id / today_str
    day_dir.mkdir(parents=True, exist_ok=True)
    report_path = day_dir / f"雷达_{strategy_name}_{today_str}.md"

    # 合并所有信号
    all_records = list(today_records) + list(watchlist_records)

    # 分类
    modules = categorize_signals(all_records)

    # 生成报告内容
    content = _build_radar_report(
        today_str=today_str,
        strategy_name=strategy_name,
        modules=modules,
    )

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[雷达报告] 已生成：{report_path}")
    return report_path


def print_radar_console(
    records: list[dict],
    watchlist: list[dict],
) -> None:
    """
    打印雷达报告到控制台（精确格式）。

    格式：
        # 📈 Oliver Kell Daily Radar Report - 2026-05-11

        ## 🟢 猎物出击 (Long Entries)
        | Ticker | Signal | Action | Stop Loss | Context |

        ## 🔵 乘胜追击 (Scale In)

        ## 🟡 利润收割 (Active Trim)

        ## 🔴 纪律防守 (Exits)

        ## 🦅 趋势逆转 (Reversal & Short)

        ## 🔭 前瞻观察池 (Watchlist)
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    all_records = list(records) + list(watchlist)
    modules = categorize_signals(all_records)

    lines: list[str] = []

    # 标题
    lines.append(f"# 📈 Oliver Kell Daily Radar Report - {today_str}")
    lines.append("")

    # ── 🟢 猎物出击 ────────────────────────────────
    lines.append("## 🟢 猎物出击 (Long Entries)")
    entries = modules["LONG_ENTRIES"]
    if entries:
        lines.append("")
        lines.append("| Ticker | Signal | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|----------|--------|")
        for r in sorted(entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            signal = r.get("信号", r.get("direction", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            # 提取简短 context
            context = _short_context(reason)
            action = "Buy" if signal in ("买入", "buy") else "Watch"
            lines.append(f"| **{ticker}** | {signal} | {action} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无新增猎物出击信号。")
    lines.append("")

    # ── 🔵 乘胜追击 ────────────────────────────────
    lines.append("## 🔵 乘胜追击 (Scale In)")
    scale_in = modules["SCALE_IN"]
    if scale_in:
        lines.append("")
        lines.append("| Ticker | Signal | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|----------|--------|")
        for r in scale_in:
            ticker = r.get("股票", r.get("symbol", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | Scale-In | Add | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无乘胜追击信号。")
    lines.append("")

    # ── 🟡 利润收割 ────────────────────────────────
    lines.append("## 🟡 利润收割 (Active Trim)")
    trim = modules["ACTIVE_TRIM"]
    if trim:
        lines.append("")
        lines.append("| Ticker | Gain | Action | Context |")
        lines.append("|--------|------|--------|---------|")
        for r in trim:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            gain_match = re.search(r'\+\-?[\d.]+%', reason)
            gain = gain_match.group() if gain_match else "—"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {gain} | Trim | {context} |")
    else:
        lines.append("> 今日无利润收割信号。")
    lines.append("")

    # ── 🔴 纪律防守 ────────────────────────────────
    lines.append("## 🔴 纪律防守 (Exits)")
    exits = modules["PASSIVE_EXIT"]
    if exits:
        lines.append("")
        lines.append("| Ticker | Exit Reason | Context |")
        lines.append("|--------|-------------|---------|")
        for r in exits:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            # 提取退出原因标签
            tag = parse_reason_tag(reason) or "exit"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | [{tag}] | {context} |")
    else:
        lines.append("> 今日无纪律防守信号。")
    lines.append("")

    # ── 🦅 趋势逆转 ────────────────────────────────
    lines.append("## 🦅 趋势逆转 (Reversal & Short)")
    reversal = modules["TREND_REVERSAL"]
    if reversal:
        lines.append("")
        lines.append("| Ticker | Reversal Type | Context |")
        lines.append("|--------|---------------|---------|")
        for r in reversal:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "reversal"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | [{tag}] | {context} |")
    else:
        lines.append("> 今日无趋势逆转信号。")
    lines.append("")

    # ── 🦅 放空出击 ────────────────────────────────
    lines.append("## 🦅 放空出击 (Short Entries)")
    short_entries = modules["SHORT_ENTRIES"]
    if short_entries:
        lines.append("")
        lines.append("| Ticker | Signal | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|----------|--------|")
        for r in sorted(short_entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            signal = r.get("信号", r.get("direction", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            action = "Short" if signal in ("做空", "short") else "Watch"
            lines.append(f"| **{ticker}** | {signal} | {action} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无放空出击信号。")
    lines.append("")

    # ── 🔭 前瞻观察池 ─────────────────────────────
    lines.append("## 🔭 前瞻观察池 (Watchlist)")
    watchlist_items = modules["WATCHLIST"]
    if watchlist_items:
        lines.append("")
        lines.append("| Ticker | Stage | Context |")
        lines.append("|--------|-------|---------|")
        for r in watchlist_items:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "watch"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | [{tag}] | {context} |")
    else:
        lines.append("> 观察池为空，市场未出现明显机会。")
    lines.append("")

    # 打印
    print("\n" + "\n".join(lines))


# ══════════════════════════════════════════════════════════
# 报告构建
# ══════════════════════════════════════════════════════════

def _build_radar_report(
    today_str: str,
    strategy_name: str,
    modules: dict[str, list[dict]],
) -> str:
    """构建雷达报告 Markdown 内容。"""
    lines: list[str] = []

    # ── 标题 ──────────────────────────────────────
    lines += [
        f"# 📈 Oliver Kell Daily Radar Report - {today_str}",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> 策略：{strategy_name}  ",
        "",
        "---",
        "",
    ]

    # ── 🟢 猎物出击 ────────────────────────────────
    lines.append("## 🟢 猎物出击 (Long Entries)")
    entries = modules["LONG_ENTRIES"]
    if entries:
        lines.append("")
        lines.append("| Ticker | Strength | Action | Stop Loss | Context |")
        lines.append("|--------|----------|--------|----------|---------|")
        for r in sorted(entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stars = "★" * int(strength) if str(strength).isdigit() else strength
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {stars} | Buy | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无新增猎物出击信号。")
    lines.append("")

    # ── 🔵 乘胜追击 ────────────────────────────────
    lines.append("## 🔵 乘胜追击 (Scale In)")
    scale_in = modules["SCALE_IN"]
    if scale_in:
        lines.append("")
        lines.append("| Ticker | Action | Stop Loss | Context |")
        lines.append("|--------|--------|----------|---------|")
        for r in scale_in:
            ticker = r.get("股票", r.get("symbol", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | Scale-In | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无乘胜追击信号。")
    lines.append("")

    # ── 🟡 利润收割 ────────────────────────────────
    lines.append("## 🟡 利润收割 (Active Trim)")
    trim = modules["ACTIVE_TRIM"]
    if trim:
        lines.append("")
        lines.append("| Ticker | Gain | Context |")
        lines.append("|--------|------|---------|")
        for r in trim:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            gain_match = re.search(r'\+\-?[\d.]+%', reason)
            gain = gain_match.group() if gain_match else "—"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {gain} | {context} |")
    else:
        lines.append("> 今日无利润收割信号。")
    lines.append("")

    # ── 🔴 纪律防守 ────────────────────────────────
    lines.append("## 🔴 纪律防守 (Exits)")
    exits = modules["PASSIVE_EXIT"]
    if exits:
        lines.append("")
        lines.append("| Ticker | Exit Reason | Context |")
        lines.append("|--------|-------------|---------|")
        for r in exits:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "exit"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | [{tag}] | {context} |")
    else:
        lines.append("> 今日无纪律防守信号。")
    lines.append("")

    # ── 🦅 趋势逆转 ────────────────────────────────
    lines.append("## 🦅 趋势逆转 (Reversal & Short)")
    reversal = modules["TREND_REVERSAL"]
    if reversal:
        lines.append("")
        lines.append("| Ticker | Reversal Type | Context |")
        lines.append("|--------|---------------|---------|")
        for r in reversal:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "reversal"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | [{tag}] | {context} |")
    else:
        lines.append("> 今日无趋势逆转信号。")
    lines.append("")

    # ── 🦅 放空出击 ────────────────────────────────
    lines.append("## 🦅 放空出击 (Short Entries)")
    short_entries = modules["SHORT_ENTRIES"]
    if short_entries:
        lines.append("")
        lines.append("| Ticker | Signal | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|----------|--------|")
        for r in sorted(short_entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            signal = r.get("信号", r.get("direction", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            action = "Short" if signal in ("做空", "short") else "Watch"
            lines.append(f"| **{ticker}** | {signal} | {action} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无放空出击信号。")
    lines.append("")

    # ── 🔭 前瞻观察池 ─────────────────────────────
    lines.append("## 🔭 前瞻观察池 (Watchlist)")
    watchlist_items = modules["WATCHLIST"]
    if watchlist_items:
        lines.append("")
        lines.append("| Ticker | Stage | Context |")
        lines.append("|--------|-------|---------|")
        for r in watchlist_items:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "watch"
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | [{tag}] | {context} |")
    else:
        lines.append("> 观察池为空，市场未出现明显机会。")
    lines.append("")

    lines.append("---")
    lines.append(f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════

def _short_context(reason: str) -> str:
    """从 reason 中提取简短上下文。"""
    if not reason:
        return ""

    # 移除方括号标签
    reason = re.sub(r'\[[^\]]+\]\s*', '', reason)

    # 提取关键数值
    ema_match = re.search(r'EMA.*?([\d.]+)', reason)
    price_match = re.search(r'\$?([\d.]+)', reason)

    parts = []
    if ema_match:
        parts.append(f"EMA: {ema_match.group(0)}")
    if price_match:
        parts.append(f"${price_match.group(1)}")

    # 移除冗余部分
    reason = reason.strip()
    if len(reason) > 50:
        reason = reason[:50] + "..."

    return reason if not parts else f"{reason} ({', '.join(parts)})"
