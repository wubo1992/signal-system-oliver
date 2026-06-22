"""
signals/report.py — 每日 Markdown 报告生成器

职责：
  1. 读取过去 7 天内的所有信号（从对应策略的 signals.csv）
  2. 对每个信号的触发原因进行结构化解读
  3. 生成 Markdown 格式的每日报告
  4. 保存到 output/{strategy_id}/YYYY-MM-DD/报告_{strategy_name}_YYYY-MM-DD.md
"""

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 路径 ───────────────────────────────────────────────────
OUTPUT_DIR = Path(__file__).parent.parent / "output"


# ══════════════════════════════════════════════════════════
# 公开接口
# ══════════════════════════════════════════════════════════

def generate_daily_report(
    today_records: list[dict],
    strategy_id: str = "v1_wizard",
    strategy_name: str = "魔法师策略V1",
) -> Path:
    """
    生成今日报告，保存到 output/{strategy_id}/YYYY-MM-DD/报告_{strategy_name}_YYYY-MM-DD.md。

    参数：
        today_records: 今天新产生的信号（来自 process_signals 的返回值）
        strategy_id:   策略文件夹 ID（如 "v1_wizard"）
        strategy_name: 策略显示名称（如 "魔法师策略V1"），用于报告标题

    返回：
        报告文件的 Path
    """
    today = datetime.now(tz=timezone.utc)
    today_str = today.strftime("%Y-%m-%d")

    # 创建输出目录
    day_dir = OUTPUT_DIR / strategy_id / today_str
    day_dir.mkdir(parents=True, exist_ok=True)
    report_path = day_dir / f"报告_{strategy_name}_{today_str}.md"

    # 读取过去 7 天的历史信号（从该策略专属 CSV）
    history = _read_recent_signals(strategy_id=strategy_id, days=7)

    # 生成报告内容
    content = _build_report(today_str, today_records, history, strategy_name)

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[报告] 已生成：{report_path}")
    return report_path


# ══════════════════════════════════════════════════════════
# 报告构建
# ══════════════════════════════════════════════════════════

def _build_report(today_str: str, today_records: list[dict], history: list[dict], strategy_name: str = "魔法师策略V1") -> str:
    lines = []

    # ── 标题 ──────────────────────────────────────────────
    lines += [
        f"# {strategy_name} 信号日报 — {today_str}",
        "",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}  ",
        f"> 报告范围：过去 7 天（{_days_ago(7)} 至 {today_str}）  ",
        f"> 策略：{strategy_name}  ",
        "> 提示：信号日期为策略检测到条件的当天，**建议次日开盘执行**",
        "",
        "---",
        "",
    ]

    # ── 今日新增信号 ───────────────────────────────────────
    today_buys   = [r for r in today_records if r.get("信号") == "买入"]
    today_sells  = [r for r in today_records if r.get("信号") == "卖出"]
    today_shorts = [r for r in today_records if r.get("信号") == "做空"]

    if not today_records:
        lines += [
            "## 今日新增信号",
            "",
            "> 今日无新信号。SEPA 条件严格，无信号是正常状态，代表当前市场没有",
            "> 同时满足趋势模板 + VCP 形态 + 突破 + 量能四重条件的股票。",
            "",
        ]
    else:
        if today_buys:
            lines += [
                "## 今日新增买入信号",
                "",
            ]
            for r in sorted(today_buys, key=lambda x: -int(x.get("强度(1-5)", 0))):
                lines += _format_signal_detail(r, is_today=True)
                lines.append("")

        if today_sells:
            lines += [
                "## 今日出场信号",
                "",
            ]
            for r in today_sells:
                lines += _format_exit_signal(r)
                lines.append("")

        if today_shorts:
            lines += [
                "## 今日做空信号",
                "",
            ]
            for r in sorted(today_shorts, key=lambda x: -int(x.get("强度(1-5)", 0))):
                lines += _format_short_signal(r, is_today=True)
                lines.append("")

    lines += ["---", ""]

    # ── 过去7天汇总表 ──────────────────────────────────────
    lines += [
        "## 过去 7 天信号汇总",
        "",
    ]

    all_recent = history  # 已经包含今天
    buys_7d   = [r for r in all_recent if r.get("信号") == "买入"]
    sells_7d  = [r for r in all_recent if r.get("信号") == "卖出"]
    shorts_7d = [r for r in all_recent if r.get("信号") == "做空"]

    if not all_recent:
        lines.append("> 过去 7 天内无任何信号记录。\n")
    else:
        if buys_7d:
            lines += [
                "### 买入信号",
                "",
                "| 日期 | 股票 | 强度 | 参考止损 | 触发摘要 |",
                "|------|------|------|----------|----------|",
            ]
            for r in sorted(buys_7d, key=lambda x: x.get("日期", ""), reverse=True):
                stars = "★" * int(r.get("强度(1-5)", 0))
                summary = _short_summary(r.get("触发原因", ""))
                lines.append(
                    f"| {r['日期']} | **{r['股票']}** | {stars} "
                    f"| {r.get('参考止损', '—')} | {summary} |"
                )
            lines.append("")

        if sells_7d:
            lines += [
                "### 出场信号",
                "",
                "| 日期 | 股票 | 持仓股数 | 出场原因 |",
                "|------|------|----------|----------|",
            ]
            for r in sorted(sells_7d, key=lambda x: x.get("日期", ""), reverse=True):
                reason_short = r.get("触发原因", "")[:45]
                shares = r.get("持仓股数", "—")
                lines.append(f"| {r['日期']} | **{r['股票']}** | {shares:>8} | {reason_short} |")
            lines.append("")

        if shorts_7d:
            lines += [
                "### 做空信号",
                "",
                "| 日期 | 股票 | 强度 | 参考止损 | 触发摘要 |",
                "|------|------|------|----------|----------|",
            ]
            for r in sorted(shorts_7d, key=lambda x: x.get("日期", ""), reverse=True):
                stars = "★" * int(r.get("强度(1-5)", 0))
                summary = _short_summary(r.get("触发原因", ""))
                lines.append(
                    f"| {r['日期']} | **{r['股票']}** | {stars} "
                    f"| {r.get('参考止损', '—')} | {summary} |"
                )
            lines.append("")

    lines += ["---", ""]

    # ── 过去7天详细解读（买入信号） ────────────────────────
    past_buys = [r for r in buys_7d if r.get("日期") != today_str]
    if past_buys:
        lines += [
            "## 过去 7 天买入信号详细解读",
            "",
            "> 以下是本周内（不含今日）触发的买入信号的完整条件解读，",
            "> 供复盘和学习参考。",
            "",
        ]
        for r in sorted(past_buys, key=lambda x: x.get("日期", ""), reverse=True):
            lines += _format_signal_detail(r, is_today=False)
            lines.append("")

    # ── 操作提醒 ────────────────────────────────────────────
    lines += [
        "---",
        "",
        "## 操作提醒",
        "",
        "| 要点 | 说明 |",
        "|------|------|",
        "| 执行时机 | 信号当天收盘后确认，**次日开盘**执行 |",
        "| 止损设置 | 买入后立即挂止损单（参考止损价），不要等收盘才检查 |",
        "| 仓位建议 | 单笔不超过总资金的 20%，分散持有 |",
        "| 无信号含义 | 当前没有满足全部条件的股票，持币观望比强行入场更安全 |",
        "",
        f"*报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════
# 单个信号详细格式化
# ══════════════════════════════════════════════════════════

def _format_signal_detail(r: dict, is_today: bool) -> list[str]:
    """生成单个买入信号的详细 Markdown 块。"""
    symbol   = r.get("股票", "?")
    date_str = r.get("日期", "?")
    strength = int(r.get("强度(1-5)", 0))
    stars    = "★" * strength + "☆" * (5 - strength)
    stop     = r.get("参考止损", "—")
    reason   = r.get("触发原因", "")

    tag = "🆕 **今日新增**" if is_today else f"📅 {date_str}"
    sections = _parse_reason(reason)

    lines = [
        f"### {tag} — 买入 {symbol}　{stars}",
        "",
        "**信号概览**",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 信号日期 | {date_str} |",
        f"| 信号方向 | 买入 |",
        f"| 信号强度 | {stars}（{strength}/5） |",
        f"| 参考止损 | {stop} |",
        f"| 建议操作 | {'明日开盘买入' if is_today else date_str + ' 次日已可执行'} |",
        "",
    ]

    # ── [趋势] ─────────────────────────────────────────────
    trend = sections.get("[趋势]", "")
    if trend:
        lines += [
            "**[趋势模板] ✓ — 8 个条件全部通过**",
            "",
        ]
        lines += _interpret_trend(trend)
        lines.append("")

    # ── [RS] ──────────────────────────────────────────────
    rs = sections.get("[RS]", "")
    if rs:
        rs_pct = _extract_number(rs)
        top_pct = round(100 - rs_pct, 0) if rs_pct else "?"
        lines += [
            f"**[相对强度 RS] ✓ — {rs}**",
            "",
            f"- 过去 12 个月涨幅在全部监控股票中排名前 {top_pct}%",
            "- RS 越高说明这只股票比市场上大多数股票都更强，是市场领涨者",
            "",
        ]

    # ── [VCP] ─────────────────────────────────────────────
    vcp = sections.get("[VCP]", "")
    if vcp:
        lines += [
            f"**[VCP 形态] ✓ — {vcp}**",
            "",
        ]
        lines += _interpret_vcp(vcp)
        lines.append("")

    # ── [突破] ────────────────────────────────────────────
    breakout = sections.get("[突破]", "")
    if breakout:
        lines += [
            f"**[枢轴点突破] ✓ — {breakout}**",
            "",
        ]
        lines += _interpret_breakout(breakout)
        lines.append("")

    # ── [量能] ────────────────────────────────────────────
    vol = sections.get("[量能]", "")
    if vol:
        vol_mult = _extract_number(vol)
        lines += [
            f"**[量能确认] ✓ — {vol}**",
            "",
            f"- 今日成交量是 20 日均量的 {vol_mult} 倍（要求 ≥ 1.5 倍）",
            "- 放量突破代表大资金真实入场，而非散户小打小闹",
        ]
        if vol_mult and vol_mult >= 2.0:
            lines.append("- ⚡ 成交量超过 2 倍，属于**强势放量**，突破可信度更高")
        lines.append("")

    # ── 风险提示 ──────────────────────────────────────────
    lines += [
        "> **风险提示**：以上均为系统自动识别的技术信号，不构成投资建议。",
        f"> 参考止损 {stop} 对应从买入价亏损约 10%，务必在买入后立即设置止损单。",
        "",
        "---",
    ]

    return lines


def _format_exit_signal(r: dict) -> list[str]:
    """格式化出场信号。"""
    symbol  = r.get("股票", "?")
    reason  = r.get("触发原因", "")
    shares = r.get("持仓股数", "—")

    lines = [
        f"### 出场 — {symbol}",
        "",
        f"**出场原因：** {reason}",
        f"**持仓股数：** {shares}",
        "",
    ]
    if "触发止损" in reason:
        lines.append("> 固定止损触发：价格跌至买入价 -10% 以下，系统自动发出卖出信号。")
    elif "追踪止盈" in reason:
        lines.append("> 追踪止盈触发：价格从持仓最高点回落超过 20%，保住已有盈利后退出。")
    elif "时间止损" in reason:
        lines.append("> 时间止损触发：持仓超过 20 天但盈利不足 3%，释放资金避免占用过久。")
    lines.append("")
    return lines


def _format_short_signal(r: dict, is_today: bool) -> list[str]:
    """格式化做空信号的详细 Markdown 块。"""
    symbol    = r.get("股票", "?")
    date_str  = r.get("日期", "?")
    strength  = int(r.get("强度(1-5)", 0))
    stars     = "★" * strength + "☆" * (5 - strength)
    stop_loss = r.get("参考止损", "—")
    reason    = r.get("触发原因", "")

    tag = "🆕 **今日新增**" if is_today else f"📅 {date_str}"
    lines = [
        f"### {tag} — 做空 {symbol}　{stars}",
        "",
        "**信号概览**",
        "",
        "| 项目 | 内容 |",
        "|------|------|",
        f"| 信号日期 | {date_str} |",
        f"| 信号方向 | 做空 |",
        f"| 信号强度 | {stars}（{strength}/5） |",
        f"| 止损价格 | {stop_loss}（buy-to-cover） |",
        f"| 建议操作 | {'明日开盘做空' if is_today else date_str + ' 次日已可执行'} |",
        "",
    ]

    # 提取触发原因中的关键信息
    if "Wedge Drop" in reason:
        lines.append("**触发条件：** Wedge Drop（楔形下跌）")
        lines.append("- 价格跌破 EMA10 和 EMA20，且两者都在下降")
        lines.append("- 建议止损：buy-to-cover at EMA20 × 1.02")
    elif "Exhaustion" in reason:
        lines.append("**触发条件：** Exhaustion Extension（衰竭延伸）")
        lines.append("- 价格超过 EMA 10% 以上且跳空上涨 ≥ 3%")
        lines.append("- 建议止损：buy-to-cover at 当日高点 × 1.02")

    lines.append("")
    lines += [
        "> **风险提示**：以上均为系统自动识别的技术信号，不构成投资建议。",
        f"> 做空止损 {stop_loss} 对应从做空价亏损约 2%，务必在做空后立即设置 buy-to-cover 止损单。",
        "",
        "---",
    ]

    return lines


# ══════════════════════════════════════════════════════════
# 触发原因解析器
# ══════════════════════════════════════════════════════════

def _parse_reason(reason: str) -> dict:
    """把 '[趋势] ... | [RS] ... | [VCP] ...' 拆分成字典。"""
    sections = {}
    parts = reason.split(" | ")
    for part in parts:
        part = part.strip()
        for key in ["[趋势]", "[RS]", "[VCP]", "[突破]", "[量能]"]:
            if part.startswith(key):
                sections[key] = part[len(key):].strip()
                break
    return sections


def _interpret_trend(trend: str) -> list[str]:
    """将趋势模板字符串转化为逐条解读。"""
    lines = []

    # 提取均线数值：SMA50(800)>SMA150(650)>SMA200(600)
    sma_match = re.search(r"SMA50\((\d+)\)>SMA150\((\d+)\)>SMA200\((\d+)\)", trend)
    if sma_match:
        s50, s150, s200 = sma_match.group(1), sma_match.group(2), sma_match.group(3)
        lines.append(f"- **均线多头排列**：SMA50({s50}) > SMA150({s150}) > SMA200({s200})")
        lines.append("  — 短中长三条均线从上到下依次排列，代表各时间周期都处于上升趋势")

    if "SMA200上升中" in trend:
        lines.append("- **SMA200 本身在上升**：长期趋势方向向上，大背景良好")

    # 52周数据
    low_match  = re.search(r"距52W低点\+?(-?\d+)%", trend)
    high_match = re.search(r"距52W高点(-?\d+)%", trend)
    if low_match:
        pct = low_match.group(1)
        lines.append(f"- **距 52 周低点 +{pct}%**：已从底部充分上涨，进入 Stage 2 上升阶段")
    if high_match:
        pct = high_match.group(1)
        note = "接近历史高点，属于强势区域" if abs(int(pct)) <= 10 else f"距高点 {pct}%"
        lines.append(f"- **距 52 周高点 {pct}%**：{note}")

    return lines


def _interpret_vcp(vcp: str) -> list[str]:
    """将 VCP 字符串转化为逐步解读。"""
    lines = []

    # 提取收缩次数
    t_match = re.search(r"VCP(\d+)T", vcp)
    n = t_match.group(1) if t_match else "?"
    lines.append(f"- **{n} 次波动收缩**：股价经历 {n} 轮整理，每轮回调幅度比上一轮更小")

    # 提取回调序列：18%→11%→5%
    depth_match = re.search(r"回调([\d%→]+)", vcp)
    if depth_match:
        seq = depth_match.group(1)
        parts = seq.split("→")
        desc = " → ".join([f"第{i+1}次 -{p}" for i, p in enumerate(parts)])
        lines.append(f"- **回调深度递减**：{desc}")
        lines.append("  — 每次调整的幅度越来越小，卖盘在逐步枯竭")

    lines.append("- **量能收缩**：每次回调期间的平均成交量也在递减，说明抛售力量减弱")

    # 末端箱体
    tail_match = re.search(r"末端([\d.]+)%箱体", vcp)
    if tail_match:
        pct = tail_match.group(1)
        lines.append(f"- **末端箱体仅 {pct}%**：最近 10 天价格波动极小（< 8%），能量高度压缩")
        lines.append("  — 这是 VCP 的关键特征：突破前的\"弹簧压紧\"状态")

    return lines


def _interpret_breakout(breakout: str) -> list[str]:
    """将突破字符串转化为逐步解读。"""
    lines = []
    pivot_match = re.search(r"\$?([\d.]+)，幅度\+?([\d.]+)%", breakout)
    if pivot_match:
        pivot = pivot_match.group(1)
        pct   = pivot_match.group(2)
        lines.append(f"- **枢轴点价格**：${pivot}（过去 30 日最高收盘价）")
        lines.append(f"- **突破幅度**：+{pct}%（要求 > 0.5%，实际 {pct}%）")
        strength_note = ""
        if float(pct) >= 3.0:
            strength_note = " — ⚡ 强势突破"
        elif float(pct) >= 1.5:
            strength_note = " — 较强突破"
        else:
            strength_note = " — 有效突破，幅度适中"
        lines.append(f"- **评估**：{float(pct):.1f}% 突破{strength_note}")
    return lines


# ══════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════

def _read_recent_signals(strategy_id: str = "v1_wizard", days: int = 7) -> list[dict]:
    """从策略专属 signals.csv 读取最近 N 天的信号记录。days=0 表示仅用于计数。"""
    signals_csv = OUTPUT_DIR / strategy_id / "signals.csv"
    if not signals_csv.exists():
        return []

    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    records = []

    with open(signals_csv, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date_str = row.get("日期", "")
            if days == 0 or date_str >= cutoff:
                records.append(dict(row))

    # 去重：同一天同一股票同一方向只保留最后一条
    seen = set()
    unique = []
    for r in reversed(records):
        key = (r.get("日期"), r.get("股票"), r.get("信号"))
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return list(reversed(unique))


def _extract_number(text: str) -> float | None:
    """从字符串中提取第一个数字。"""
    m = re.search(r"[\d.]+", text)
    return float(m.group()) if m else None


def _short_summary(reason: str) -> str:
    """提取触发原因的简短摘要（VCP + 突破部分）。"""
    sections = _parse_reason(reason)
    parts = []
    vcp = sections.get("[VCP]", "")
    if vcp:
        t_match = re.search(r"VCP(\d+)T", vcp)
        if t_match:
            parts.append(f"VCP{t_match.group(1)}T")
    breakout = sections.get("[突破]", "")
    if breakout:
        pct_match = re.search(r"幅度\+?([\d.]+)%", breakout)
        if pct_match:
            parts.append(f"突破+{pct_match.group(1)}%")
    vol = sections.get("[量能]", "")
    if vol:
        mult_match = re.search(r"([\d.]+)倍", vol)
        if mult_match:
            parts.append(f"量{mult_match.group(1)}x")
    return " | ".join(parts) if parts else reason[:40]


def _days_ago(n: int) -> str:
    return (datetime.now(tz=timezone.utc) - timedelta(days=n)).strftime("%Y-%m-%d")
