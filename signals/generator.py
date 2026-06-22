"""
signals/generator.py — 信号输出模块

职责：接收 SIGNAL 事件，格式化后输出到控制台和/或 CSV 文件。

输出格式（来自 SYSTEM_SPEC.md）：
    时间       | 股票 | 信号 | 强度  | 触发原因           | 参考止损
    2026-03-03 | NVDA | 买入 | ★★★★ | 突破30日高点，...  | $109.02

输出路径：
    output/{strategy_id}/signals.csv
    （每个策略独立存储，互不干扰）
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from events import EventQueue, EventType, SignalEvent

# 输出目录（父目录）
OUTPUT_DIR = Path(__file__).parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# 方向翻译
_DIRECTION_CN = {
    "buy": "买入",
    "sell": "卖出",
    "watch": "观望",
    "short": "做空",
}

# CSV 列名
_CSV_HEADERS = ["日期", "股票", "信号", "强度(1-5)", "触发原因", "参考止损", "持仓股数"]


def process_signals(
    queue: EventQueue,
    config: dict,
    strategy_id: str = "v1_wizard",
) -> list[dict]:
    """
    从事件队列中取出所有 SIGNAL 事件，输出到控制台和 CSV。

    参数：
        queue:       事件队列
        config:      从 config.yaml 读取的配置
        strategy_id: 策略文件夹 ID（如 "v1_wizard"），决定 CSV 存储路径

    返回：
        当次处理的所有信号记录（字典列表）
    """
    output_cfg = config.get("output", {})
    print_to_console = output_cfg.get("print_to_console", True)
    save_to_csv = output_cfg.get("save_to_csv", True)

    records = []
    while not queue.empty():
        event = queue.get(timeout=0.05)
        if event is None:
            break
        if event.type == EventType.SIGNAL:
            record = _event_to_record(event)
            records.append(record)

    if not records:
        return []

    if print_to_console:
        _print_table(records)

    if save_to_csv:
        _append_to_csv(records, strategy_id)

    return records


def format_signals(signals: list[SignalEvent]) -> list[dict]:
    """
    把 SignalEvent 列表直接转换为记录（不经过队列）。
    用于回测引擎直接调用。
    """
    return [_event_to_record(s) for s in signals]


def _event_to_record(event: SignalEvent) -> dict:
    """把 SignalEvent 转换成可输出的字典。"""
    date_str = event.timestamp.strftime("%Y-%m-%d")
    direction = event.data.get("direction", "watch")
    strength = event.data.get("strength", 0)
    reason = event.data.get("reason", "")
    stop_loss = event.data.get("stop_loss")
    shares = event.data.get("shares", 0.0)

    stop_str = f"${stop_loss:.2f}" if stop_loss is not None else "—"
    stars = "★" * strength + "☆" * (5 - strength)

    # 持仓股数显示
    if direction == "sell":
        if isinstance(shares, (int, float)) and shares > 0:
            shares_str = f"{int(shares)}股"
        elif shares == "半仓":
            shares_str = "半仓"
        else:
            shares_str = "（请填写持仓数）"
    else:
        shares_str = "—"

    return {
        "日期": date_str,
        "股票": event.symbol,
        "信号": _DIRECTION_CN.get(direction, direction),
        "强度(1-5)": strength,
        "强度星级": stars,
        "触发原因": reason,
        "参考止损": stop_str,
        "持仓股数": shares_str,
    }


def _print_table(records: list[dict]) -> None:
    """把信号以表格形式打印到控制台。"""
    # 分组：买入、卖出、做空信号分开显示
    buy_records = [r for r in records if r["信号"] == "买入"]
    sell_records = [r for r in records if r["信号"] == "卖出"]
    short_records = [r for r in records if r["信号"] == "做空"]

    print()
    print("=" * 75)
    print("信号报告")
    print("=" * 75)

    if buy_records:
        print(f"\n【买入信号】共 {len(buy_records)} 个")
        print(f"{'日期':<12} {'股票':<8} {'强度':<8} {'参考止损':<10} 触发原因")
        print("-" * 75)
        for r in sorted(buy_records, key=lambda x: -x["强度(1-5)"]):
            print(
                f"{r['日期']:<12} {r['股票']:<8} {r['强度星级']:<8} "
                f"{r['参考止损']:<10} {r['触发原因']}"
            )

    if sell_records:
        print(f"\n【出场信号】共 {len(sell_records)} 个")
        print(f"{'日期':<12} {'股票':<8} {'持仓股数':<14} 原因")
        print("-" * 75)
        for r in sell_records:
            print(f"{r['日期']:<12} {r['股票']:<8} {r['持仓股数']:<14} {r['触发原因']}")

    if short_records:
        print(f"\n【做空信号】共 {len(short_records)} 个")
        print(f"{'日期':<12} {'股票':<8} {'强度':<8} {'参考止损':<10} 触发原因")
        print("-" * 75)
        for r in sorted(short_records, key=lambda x: -x["强度(1-5)"]):
            print(
                f"{r['日期']:<12} {r['股票']:<8} {r['强度星级']:<8} "
                f"{r['参考止损']:<10} {r['触发原因']}"
            )

    if not buy_records and not sell_records and not short_records:
        print("\n今日无有效信号")

    print("=" * 75)
    print()


def _append_to_csv(records: list[dict], strategy_id: str = "v1_wizard") -> None:
    """把信号追加写入 CSV 文件（去重后写入，同一日同一股票同一方向只保留一条）。"""
    strategy_dir = OUTPUT_DIR / strategy_id
    strategy_dir.mkdir(parents=True, exist_ok=True)
    signals_csv = strategy_dir / "signals.csv"

    # 读取已有记录，建立去重 key 集合
    existing_keys: set[tuple] = set()
    if signals_csv.exists():
        with open(signals_csv, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_keys.add((row["日期"], row["股票"], row["信号"]))

    # 过滤掉已存在的记录
    new_records = [
        r for r in records
        if (r["日期"], r["股票"], r["信号"]) not in existing_keys
    ]

    if not new_records:
        print(f"[输出] 无新信号需要写入（均已存在）")
        return

    file_exists = signals_csv.exists()
    with open(signals_csv, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=_CSV_HEADERS,
            extrasaction="ignore",
        )
        if not file_exists:
            writer.writeheader()

        for r in new_records:
            writer.writerow({
                "日期": r["日期"],
                "股票": r["股票"],
                "信号": r["信号"],
                "强度(1-5)": r["强度(1-5)"],
                "触发原因": r["触发原因"],
                "参考止损": r["参考止损"],
                "持仓股数": r.get("持仓股数", "—"),
            })

    print(f"[输出] 信号已保存到 {signals_csv}（写入 {len(new_records)} 条新记录，去重 {len(records) - len(new_records)} 条）")
