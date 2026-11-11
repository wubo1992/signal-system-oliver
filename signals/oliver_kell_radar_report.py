"""
signals/oliver_kell_radar_report.py — Oliver Kell 每日雷达报告

8 模块分类：
    🟢 猎物出击 (Long Entries): [Wedge Pop], [EMA Crossback], [Base n' Break] direction=buy
    🔵 乘胜追击 (Scale In): [Batch 2]
    🟡 利润收割 (Active Trim): [Extension Sell] 涨幅 > 100%
    🔴 纪律防守 (Exits): [EMA20 Break], [Hard Stop 8%], [Ignite Bar Stop]
    🦅 趋势逆转 (Trend Reversal): [Wedge Drop], [Failed Breakout], [Time Stop], [3x Trapped]
    🐂 底部机会 (Reversal Bottom): [Reversal Extension]
    🦅 放空出击 (Short Entries): [Wedge Drop Short], [Exhaustion Short]
    🔭 前瞻观察池 (Watchlist): direction=watch OR [Base Tightening]
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
            "RS (10D)": r.data.get("rs_value_10d"),
            "RS (20D)": r.data.get("rs_value"),
            "RS (10W)": r.data.get("rs_value_10w"),
            "量比": r.data.get("volume_ratio"),
            "RS评级": r.data.get("rs_rating"),
            "RS倍数": r.data.get("rs_ratio"),
            "Weinstein阶段": r.data.get("weinstein_stage"),
        }
    return {}


def _format_rs(rs_value) -> str:
    """Render RS 数值（倍数形式：1.0329 = 跑赢大盘 3.29%）。"""
    if rs_value is None:
        return "—"
    try:
        return f"{float(rs_value):.4f}"
    except (TypeError, ValueError):
        return str(rs_value) if rs_value != "" else "—"


def _format_rs_triple(r) -> tuple[str, str, str]:
    """同时取 10D、20D 和 10W RS 数值（兼容 dict/SignalEvent）。"""
    if hasattr(r, "data"):
        rs_10d = r.data.get("rs_value_10d")
        rs_20d = r.data.get("rs_value")
        rs_10w = r.data.get("rs_value_10w")
    else:
        rs_10d = r.get("RS (10D)", r.get("rs_value_10d"))
        rs_20d = r.get("RS (20D)", r.get("rs_value"))
        rs_10w = r.get("RS (10W)", r.get("rs_value_10w"))
    return _format_rs(rs_10d), _format_rs(rs_20d), _format_rs(rs_10w)


def _format_rs_pair(r) -> tuple[str, str]:
    """同时取 20D 和 10W RS 数值（兼容 dict/SignalEvent）。"""
    if hasattr(r, "data"):
        rs_20d = r.data.get("rs_value")
        rs_10w = r.data.get("rs_value_10w")
    else:
        rs_20d = r.get("RS (20D)", r.get("rs_value"))
        rs_10w = r.get("RS (10W)", r.get("rs_value_10w"))
    return _format_rs(rs_20d), _format_rs(rs_10w)


def _format_oneil_pair(r) -> tuple[str, str]:
    """同时取 O'Neil RS 评级（1-99 百分位）与 RS 倍数（vs SPY 252 日）。"""
    if hasattr(r, "data"):
        rating = r.data.get("rs_rating")
        mult = r.data.get("rs_ratio")
    else:
        rating = r.get("RS评级")
        mult = r.get("RS倍数")
    rating_str = "—"
    if rating is not None:
        try:
            rating_str = f"{int(float(rating))}"
        except (TypeError, ValueError):
            rating_str = str(rating)
    return rating_str, _format_rs(mult)


def _format_stage(r) -> str:
    """Weinstein 四阶段标签（兼容 dict / SignalEvent）。"""
    if hasattr(r, "data"):
        stage = r.data.get("weinstein_stage")
    else:
        stage = r.get("Weinstein阶段")
    if not stage:
        return "—"
    return str(stage)


def _format_vol(vol) -> str:
    """Render 量比（兼容 None/int/float/str）。"""
    if vol is None:
        return "—"
    try:
        return f"{float(vol):.1f}x"
    except (TypeError, ValueError):
        s = str(vol)
        return s if s else "—"


def _dedupe_records(records: list) -> list:
    """按 (股票, 信号) 去重，保留第一次出现的记录。

    修复 main.py 同时传入 records 和 watchlist_records 导致同一信号出现两次的 bug。
    兼容 dict 和 SignalEvent；将中英信号值（"观望"/"watch"）归一化为同一 canonical 字符串。
    """
    # canonical 归一化：dict 记录用中文（"观望"/"买入"/"卖出"/"做空"），
    # SignalEvent 用英文（"watch"/"buy"/"sell"/"short"），按类映射到同一 key
    _DIRECTION_CANONICAL = {
        "观望": "watch", "watch": "watch",
        "买入": "buy", "buy": "buy",
        "卖出": "sell", "sell": "sell",
        "做空": "short", "short": "short",
    }
    seen: set = set()
    out: list = []
    for r in records:
        if hasattr(r, "data"):
            symbol = getattr(r, "symbol", "?")
            signal_raw = (r.data or {}).get("direction", "?")
        else:
            symbol = r.get("股票", r.get("symbol", "?"))
            signal_raw = r.get("信号", r.get("direction", "?"))
        signal = _DIRECTION_CANONICAL.get(signal_raw, signal_raw)
        key = (symbol, signal)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def categorize_signals(records: list) -> dict[str, list[dict]]:
    """
    将信号记录分类到 8 个模块。

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
        "REVERSAL_BOTTOM": [],   # 🐂 底部机会 (Reversal Extension)
        "WATCHLIST": [],         # 🔭 前瞻观察池
        "SHORT_ENTRIES": [],     # 🦅 放空出击 (Short Entries)
    }

    for r in records:
        rec = _record_to_dict(r)
        direction = rec.get("信号", rec.get("direction", ""))
        reason = rec.get("触发原因", rec.get("reason", ""))
        cycle_stage = rec.get("cycle_stage", parse_reason_tag(reason))
        signal_type = rec.get("信号", "")

        # Reversal Extension → 底部机会（独立模块）
        if cycle_stage == "reversal_extension" or "Reversal Extension" in reason:
            modules["REVERSAL_BOTTOM"].append(rec)
            continue

        # Watchlist / 观望方向（base_tightening 等）
        if direction == "watch" or "Base Tightening" in reason:
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
    生成 8 模块雷达报告，保存到 output/{strategy_id}/YYYY-MM-DD/雷达_{strategy_name}_YYYY-MM-DD.md

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

    # 合并所有信号（按 (股票, 信号) 去重，避免 watchlist 重复传入造成重复行）
    all_records = _dedupe_records(list(today_records) + list(watchlist_records))

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
        | Ticker | Strength | RS | Vol Ratio | Action | Stop Loss | Context |

        ## 🔵 乘胜追击 (Scale In)
        | Ticker | RS | Vol Ratio | Action | Stop Loss | Context |

        ## 🟡 利润收割 (Active Trim)
        | Ticker | RS | Vol Ratio | Gain | Context |

        ## 🔴 纪律防守 (Exits)
        | Ticker | RS | Vol Ratio | Exit Reason | Context |

        ## 🦅 趋势逆转 (Reversal & Short)
        | Ticker | RS | Vol Ratio | Reversal Type | Context |

        ## 🐂 底部机会 (Reversal Bottom)
        | Ticker | RS | Dist from EMA20 | Cum Rebound (since bottom) | Vol Ratio | Stop | Context |

        ## 🦅 放空出击 (Short Entries)
        | Ticker | RS | Vol Ratio | Signal | Action | Stop Loss | Context |

        ## 🔭 前瞻观察池 (Watchlist)
        | Ticker | RS | Vol Ratio | Stage | Context |
    """
    today_str = datetime.now().strftime("%Y-%m-%d")

    all_records = _dedupe_records(list(records) + list(watchlist))
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
        lines.append("| Ticker | Strength | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Action | Stop Loss | Context |")
        lines.append("|--------|----------|--------|--------|--------|--------|--------|-----------|--------|----------|---------|")
        for r in sorted(entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            signal = r.get("信号", r.get("direction", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            # 提取简短 context
            context = _short_context(reason)
            action = "Buy" if signal in ("买入", "buy") else "Watch"
            stars = "★" * int(strength) + "☆" * (5 - int(strength)) if isinstance(strength, int) else strength
            lines.append(f"| **{ticker}** | {stars} | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | {action} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无新增猎物出击信号。")
    lines.append("")

    # ── 🔵 乘胜追击 ────────────────────────────────
    lines.append("## 🔵 乘胜追击 (Scale In)")
    scale_in = modules["SCALE_IN"]
    if scale_in:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|--------|----------|---------|")
        for r in scale_in:
            ticker = r.get("股票", r.get("symbol", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | Add | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无乘胜追击信号。")
    lines.append("")

    # ── 🟡 利润收割 ────────────────────────────────
    lines.append("## 🟡 利润收割 (Active Trim)")
    trim = modules["ACTIVE_TRIM"]
    if trim:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Gain | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|------|---------|")
        for r in trim:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            gain_match = re.search(r'\+\-?[\d.]+%', reason)
            gain = gain_match.group() if gain_match else "—"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | {gain} | {context} |")
    else:
        lines.append("> 今日无利润收割信号。")
    lines.append("")

    # ── 🔴 纪律防守 ────────────────────────────────
    lines.append("## 🔴 纪律防守 (Exits)")
    exits = modules["PASSIVE_EXIT"]
    if exits:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Exit Reason | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|-------------|---------|")
        for r in exits:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            # 提取退出原因标签
            tag = parse_reason_tag(reason) or "exit"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | [{tag}] | {context} |")
    else:
        lines.append("> 今日无纪律防守信号。")
    lines.append("")

    # ── 🦅 趋势逆转 ────────────────────────────────
    lines.append("## 🦅 趋势逆转 (Reversal & Short)")
    reversal = modules["TREND_REVERSAL"]
    if reversal:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Reversal Type | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|---------------|---------|")
        for r in reversal:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "reversal"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | [{tag}] | {context} |")
    else:
        lines.append("> 今日无趋势逆转信号。")
    lines.append("")

    # ── 🐂 底部机会 (Reversal Bottom) ──────────────
    lines.append("## 🐂 底部机会 (Reversal Bottom)")
    reversal_bottom = modules["REVERSAL_BOTTOM"]
    if reversal_bottom:
        lines.append("")
        lines.append("> 最近20个交易日内曾低于 EMA20 10% 以上，累计反弹 ≥10% + 当日反弹 ≥3% 的底部观察股，等待 Wedge Pop 确认。")
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Dist from EMA20 | Cum Rebound (since bottom) | Vol Ratio | Stop | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------------|------------------------------|-----------|------|---------|")
        for r in sorted(reversal_bottom, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            # 从 reason 提取数值
            dist_match = re.search(r'Current EMA20 distance:\s*([+-]?[\d.]+)%', reason)
            snap_match = re.search(r'Cum rebound \(since bottom (\d+)d ago\):\s+\+?([\d.]+)%', reason)
            vol_match = re.search(r'vol\s+([\d.]+)x', reason)
            dist = f"{dist_match.group(1)}%" if dist_match else "—"
            snap = f"+{snap_match.group(2)}% ({snap_match.group(1)}d)" if snap_match else "—"
            vol = f"{vol_match.group(1)}x" if vol_match else "—"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {dist} | {snap} | {vol} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无底部机会信号。")
    lines.append("")

    # ── 🦅 放空出击 ────────────────────────────────
    lines.append("## 🦅 放空出击 (Short Entries)")
    short_entries = modules["SHORT_ENTRIES"]
    if short_entries:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Signal | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|--------|--------|----------|---------|")
        for r in sorted(short_entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            signal = r.get("信号", r.get("direction", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            context = _short_context(reason)
            action = "Short" if signal in ("做空", "short") else "Watch"
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | {signal} | {action} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无放空出击信号。")
    lines.append("")

    # ── 🔭 前瞻观察池 ─────────────────────────────
    lines.append("## 🔭 前瞻观察池 (Watchlist)")
    watchlist_items = modules["WATCHLIST"]
    if watchlist_items:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Stage | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|-------|---------|")
        for r in watchlist_items:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "watch"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | [{tag}] | {context} |")
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
        lines.append("| Ticker | Strength | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Action | Stop Loss | Context |")
        lines.append("|--------|----------|--------|--------|--------|--------|--------|-----------|--------|----------|---------|")
        for r in sorted(entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            strength = r.get("强度(1-5)", r.get("strength", "?"))
            stars = "★" * int(strength) if str(strength).isdigit() else strength
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {stars} | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | Buy | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无新增猎物出击信号。")
    lines.append("")

    # ── 🔵 乘胜追击 ────────────────────────────────
    lines.append("## 🔵 乘胜追击 (Scale In)")
    scale_in = modules["SCALE_IN"]
    if scale_in:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|--------|----------|---------|")
        for r in scale_in:
            ticker = r.get("股票", r.get("symbol", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | Scale-In | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无乘胜追击信号。")
    lines.append("")

    # ── 🟡 利润收割 ────────────────────────────────
    lines.append("## 🟡 利润收割 (Active Trim)")
    trim = modules["ACTIVE_TRIM"]
    if trim:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Gain | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|------|---------|")
        for r in trim:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            gain_match = re.search(r'\+\-?[\d.]+%', reason)
            gain = gain_match.group() if gain_match else "—"
            context = _short_context(reason)
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | {gain} | {context} |")
    else:
        lines.append("> 今日无利润收割信号。")
    lines.append("")

    # ── 🔴 纪律防守 ────────────────────────────────
    lines.append("## 🔴 纪律防守 (Exits)")
    exits = modules["PASSIVE_EXIT"]
    if exits:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Exit Reason | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|-------------|---------|")
        for r in exits:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "exit"
            context = _short_context(reason)
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | [{tag}] | {context} |")
    else:
        lines.append("> 今日无纪律防守信号。")
    lines.append("")

    # ── 🦅 趋势逆转 ────────────────────────────────
    lines.append("## 🦅 趋势逆转 (Reversal & Short)")
    reversal = modules["TREND_REVERSAL"]
    if reversal:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Reversal Type | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|---------------|---------|")
        for r in reversal:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "reversal"
            context = _short_context(reason)
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | [{tag}] | {context} |")
    else:
        lines.append("> 今日无趋势逆转信号。")
    lines.append("")

    # ── 🐂 底部机会 (Reversal Bottom) ──────────────
    lines.append("## 🐂 底部机会 (Reversal Bottom)")
    reversal_bottom = modules["REVERSAL_BOTTOM"]
    if reversal_bottom:
        lines.append("")
        lines.append("> 最近20个交易日内曾低于 EMA20 10% 以上，累计反弹 ≥10% + 当日反弹 ≥3% 的底部观察股，等待 Wedge Pop 确认。")
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Dist from EMA20 | Cum Rebound (since bottom) | Vol Ratio | Stop | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------------|------------------------------|-----------|------|---------|")
        for r in sorted(reversal_bottom, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            # 从 reason 提取数值
            dist_match = re.search(r'Current EMA20 distance:\s*([+-]?[\d.]+)%', reason)
            snap_match = re.search(r'Cum rebound \(since bottom (\d+)d ago\):\s+\+?([\d.]+)%', reason)
            vol_match = re.search(r'vol\s+([\d.]+)x', reason)
            dist = f"{dist_match.group(1)}%" if dist_match else "—"
            snap = f"+{snap_match.group(2)}% ({snap_match.group(1)}d)" if snap_match else "—"
            vol = f"{vol_match.group(1)}x" if vol_match else "—"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            context = _short_context(reason)
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {dist} | {snap} | {vol} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无底部机会信号。")
    lines.append("")

    # ── 🦅 放空出击 ────────────────────────────────
    lines.append("## 🦅 放空出击 (Short Entries)")
    short_entries = modules["SHORT_ENTRIES"]
    if short_entries:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Signal | Action | Stop Loss | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|--------|--------|----------|---------|")
        for r in sorted(short_entries, key=lambda x: -int(x.get("强度(1-5)", x.get("strength", 0)))):
            ticker = r.get("股票", r.get("symbol", "?"))
            signal = r.get("信号", r.get("direction", "?"))
            stop_loss = r.get("参考止损", r.get("stop_loss", "—"))
            reason = r.get("触发原因", r.get("reason", ""))
            context = _short_context(reason)
            action = "Short" if signal in ("做空", "short") else "Watch"
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | {signal} | {action} | {stop_loss} | {context} |")
    else:
        lines.append("> 今日无放空出击信号。")
    lines.append("")

    # ── 🔭 前瞻观察池 ─────────────────────────────
    lines.append("## 🔭 前瞻观察池 (Watchlist)")
    watchlist_items = modules["WATCHLIST"]
    if watchlist_items:
        lines.append("")
        lines.append("| Ticker | RS 10D | RS 20D | RS 10W | O'Neil RS | RS Mult | Weinstein | Vol Ratio | Stage | Context |")
        lines.append("|--------|--------|--------|--------|--------|--------|--------|-----------|-------|---------|")
        for r in watchlist_items:
            ticker = r.get("股票", r.get("symbol", "?"))
            reason = r.get("触发原因", r.get("reason", ""))
            tag = parse_reason_tag(reason) or "watch"
            context = _short_context(reason)
            rs_10d_str, rs_str, rs_10w_str = _format_rs_triple(r)
            rating_str, mult_str = _format_oneil_pair(r)
            stage_str = _format_stage(r)
            vol_str = _format_vol(r.get("量比", r.get("volume_ratio")))
            lines.append(f"| **{ticker}** | {rs_10d_str} | {rs_str} | {rs_10w_str} | {rating_str} | {mult_str} | {stage_str} | {vol_str} | [{tag}] | {context} |")
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
    """
    从 reason 中提取简短上下文。

    reason 用 " | " 分段（"[EMA Crossback] Entry | [RS-10D] 1.0676 | ..."），
    裸竖线会被 Markdown 当成列分隔符，把这一行冲出表格 —— 所以这里把分段
    拼成 " / "，并保证返回值里不含竖线。
    """
    if not reason:
        return ""

    parts = []
    for segment in reason.split("|"):
        segment = segment.strip()
        if not segment:
            continue
        # "[RS-10D] 1.0676" → "RS-10D 1.0676"
        segment = re.sub(r"^\[([^\]]+)\]\s*", r"\1 ", segment)
        parts.append(segment)

    # 按段落截断，不要在数字中间砍断
    out: list[str] = []
    total = 0
    for part in parts:
        if total and total + len(part) + 3 > 70:
            out.append("…")
            break
        out.append(part)
        total += len(part) + 3

    return " / ".join(out).replace("|", "\\|")