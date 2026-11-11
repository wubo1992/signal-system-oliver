"""
signals/log_generator.py — v_oliver_kell 信号日志生成器

每次 live test 后自动生成/更新 SIGNALS_LOG.md，
按日期记录多头和空头信号，方便复盘和业绩复核。

CSV 表头是中文（且带 BOM），读取时统一归一化成内部英文 key，
下游不再到处改列名。
"""

from datetime import datetime
from pathlib import Path
import csv
import re

OUTPUT_DIR = Path(__file__).parent.parent / "output"
SIGNALS_LOG_FILE = OUTPUT_DIR / "SIGNALS_LOG.md"

# 策略 ID
ALL_STRATEGIES = ["v_oliver_kell"]

# 策略显示名称
STRATEGY_NAMES = {
    "v_oliver_kell": "v_oliver_kell",
}

# signals.csv 的中文表头 → 本模块内部统一使用的英文 key。
_CSV_COLUMNS = {
    "日期": "date",
    "股票": "symbol",
    "信号": "signal",
    "触发原因": "reason",
    "强度(1-5)": "strength",
    "参考止损": "stop_loss",
    "RS (10D)": "rs_10d",
    "RS (20D)": "rs_20d",
    "RS (10W)": "rs_10w",
    "量比": "volume_ratio",
    "RS评级": "rs_rating",
    "RS倍数": "rs_ratio",
    "Weinstein阶段": "weinstein_stage",
}

# 信号值 → 多 / 空。
# 观望归入多头：形态成立即候选，只是还没到确认开仓那一步。
_SIGNAL_TO_SIDE = {
    "买入": "long",
    "观望": "long",
    "卖出": "short",
    "做空": "short",
}


def _cell(text) -> str:
    """Markdown 表格单元格转义：裸竖线会把一行冲出表格。"""
    if text is None or text == "":
        return "—"
    return str(text).replace("|", "\\|").replace("\n", " ").replace("\r", " ")


def _pattern(reason: str) -> str:
    """取触发原因里的第一个策略标签（如 'EMA Crossback' / 'Wedge Drop'）。"""
    if not reason:
        return "—"
    m = re.match(r"\s*\[([^\]]+)\]", reason)
    return m.group(1) if m else "—"


def _summary(reason: str, limit: int = 140) -> str:
    """触发原因摘要：分段用 ' / ' 连接，截断到 limit 字符。"""
    if not reason:
        return "—"
    parts = []
    for segment in reason.split("|"):
        segment = segment.strip()
        if segment:
            parts.append(segment)
    text = " / ".join(parts)
    if len(text) > limit:
        text = text[:limit - 1] + "…"
    return text


def _read_rows(strategy_id: str) -> list[dict]:
    """读取策略 signals.csv 的全部行，归一化成内部英文 key。"""
    csv_path = OUTPUT_DIR / strategy_id / "signals.csv"
    if not csv_path.exists():
        return []

    rows: list[dict] = []
    # utf-8-sig：signals.csv 的表头第一个字段带 BOM，用 utf-8 读会变成
    # '﻿日期'，列名对不上。
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        for raw in csv.DictReader(f):
            row = {_CSV_COLUMNS.get(k, k): v for k, v in raw.items() if k is not None}
            row["date"] = (row.get("date") or "")[:10]
            if row["date"]:
                rows.append(row)
    return rows


def load_signals_from_csv(strategy_id: str, date_str: str) -> tuple[list[dict], list[dict]]:
    """
    从策略的 signals.csv 加载指定日期的多头和空头信号。

    返回: (long_signals, short_signals)
    """
    long_signals: list[dict] = []
    short_signals: list[dict] = []

    for row in _read_rows(strategy_id):
        if row["date"] != date_str:
            continue
        side = _SIGNAL_TO_SIDE.get((row.get("signal") or "").strip())
        if side == "long":
            long_signals.append(row)
        elif side == "short":
            short_signals.append(row)

    return long_signals, short_signals


def _summary_table(rows: list[dict], side_label: str) -> list[str]:
    """多头 / 空头共用的汇总表。"""
    lines = [
        f"### {side_label}信号汇总",
        "",
        "| 股票 | 信号 | 强度 | 形态 | Weinstein | RS 10D | RS 20D | RS 10W | 量比 | 参考止损 |",
        "|------|------|------|------|------------|--------|--------|--------|------|----------|",
    ]
    for r in sorted(rows, key=lambda x: (-int(x.get("strength") or 0), x.get("symbol", ""))):
        lines.append(
            f"| **{r.get('symbol', '')}** | {r.get('signal', '—')} | {r.get('strength', '—')} "
            f"| {_cell(_pattern(r.get('reason', '')))} "
            f"| {_cell(r.get('weinstein_stage') or '—')} "
            f"| {r.get('rs_10d') or '—'} | {r.get('rs_20d') or '—'} | {r.get('rs_10w') or '—'} "
            f"| {r.get('volume_ratio') or '—'} | {r.get('stop_loss') or '—'} |"
        )
    lines.append("")
    return lines


def _detail_table(rows: list[dict]) -> list[str]:
    """触发原因详情（每只股票一段）。"""
    lines = ["### 信号详情", ""]
    for r in sorted(rows, key=lambda x: (-int(x.get("strength") or 0), x.get("symbol", ""))):
        lines += [
            f"#### {r.get('symbol', '')} — {r.get('signal', '')}",
            "",
            f"- 形态：{_pattern(r.get('reason', ''))}",
            f"- 强度：{r.get('strength', '—')}/5",
            f"- 参考止损：{r.get('stop_loss') or '—'}",
            f"- 触发摘要：{_summary(r.get('reason', ''))}",
            "",
        ]
    return lines


def generate_daily_section(
    date_str: str,
    long_signals: list[dict],
    short_signals: list[dict],
) -> str:
    """生成某一天的信号汇总部分"""

    lines = [f"## {date_str}", ""]

    if long_signals:
        lines += _summary_table(long_signals, "多头")
        lines += _detail_table(long_signals)
    if short_signals:
        lines += _summary_table(short_signals, "空头")
        lines += _detail_table(short_signals)

    if not long_signals and not short_signals:
        lines += ["（当日无信号）", ""]

    lines.append("---")
    lines.append("")

    return "\n".join(lines)


def _header() -> str:
    """日志文件头部。"""
    return f"""# 信号汇总日志（v_oliver_kell）

> 自动生成，每次 live test 后更新
> 用于复盘和业绩复核
> 最后更新：{datetime.now().strftime("%Y-%m-%d %H:%M")}

---

"""


def _strip_old_header(content: str) -> str:
    """
    剥掉旧头部。

    按「行首一级标题」匹配，不写死标题文本——历史文件的头是
    「# 全策略信号汇总日志」，写死判断就剥不掉，新旧两个头会叠在一起。
    """
    if content.startswith("# "):
        match = re.search(r"^---\n+", content, re.MULTILINE)
        if match:
            return content[match.end():]
    return content


def update_signals_log(date_str: str | None = None) -> None:
    """
    更新信号汇总日志。

    参数:
        date_str: 日期字符串，默认使用今天
    """
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    # 加载所有策略的信号
    all_long: dict[str, list] = {}
    all_short: dict[str, list] = {}

    for strategy in ALL_STRATEGIES:
        longs, shorts = load_signals_from_csv(strategy, date_str)
        if longs:
            all_long[strategy] = longs
        if shorts:
            all_short[strategy] = shorts

    # 如果没有任何信号，跳过
    if not all_long and not all_short:
        print(f"[信号日志] {date_str} 无信号，跳过更新")
        return

    long_rows = [s for sigs in all_long.values() for s in sigs]
    short_rows = [s for sigs in all_short.values() for s in sigs]
    new_section = generate_daily_section(date_str, long_rows, short_rows)

    # 读取现有文件
    if SIGNALS_LOG_FILE.exists():
        with open(SIGNALS_LOG_FILE, "r", encoding="utf-8") as f:
            existing_content = f.read()
    else:
        existing_content = ""

    # 检查该日期是否已存在
    if f"## {date_str}" in existing_content:
        pattern = rf"## {date_str}\n.*?(?=\n## |\n\*文件生成|$)"
        existing_content = re.sub(pattern, new_section.rstrip("\n") + "\n", existing_content, flags=re.DOTALL)
        print(f"[信号日志] 更新 {date_str} 的信号记录")
    else:
        if "## " in existing_content:
            first_section_pos = existing_content.find("## ")
            existing_content = (
                existing_content[:first_section_pos] +
                new_section + "\n" +
                existing_content[first_section_pos:]
            )
        else:
            existing_content = existing_content.rstrip() + "\n\n" + new_section
        print(f"[信号日志] 添加 {date_str} 的信号记录")

    existing_content = _strip_old_header(existing_content)

    # 写入文件
    with open(SIGNALS_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(_header() + existing_content)

    print(f"[信号日志] 已保存到 {SIGNALS_LOG_FILE}")


def rebuild_signals_log() -> int:
    """
    从 signals.csv 全量重建 SIGNALS_LOG.md。

    日期倒序（新的在顶部）。逐日调用 update_signals_log 也能得到同样结果，
    但那样要把 CSV 重读几百遍 —— 重建时一次读完，按日期分组。

    返回重建出的日期数。
    """
    by_date: dict[str, tuple[list[dict], list[dict]]] = {}
    for row in _read_rows(ALL_STRATEGIES[0]):
        side = _SIGNAL_TO_SIDE.get((row.get("signal") or "").strip())
        longs, shorts = by_date.setdefault(row["date"], ([], []))
        if side == "long":
            longs.append(row)
        elif side == "short":
            shorts.append(row)

    # 升序生成，倒序拼接 → 最终是倒序（最新在顶部）
    sections = [
        generate_daily_section(date_str, by_date[date_str][0], by_date[date_str][1])
        for date_str in sorted(by_date)
    ]

    with open(SIGNALS_LOG_FILE, "w", encoding="utf-8") as f:
        f.write(_header() + "\n".join(reversed(sections)))

    print(f"[信号日志] 已重建 {len(sections)} 个日期 → {SIGNALS_LOG_FILE}")
    return len(sections)


if __name__ == "__main__":
    update_signals_log()
