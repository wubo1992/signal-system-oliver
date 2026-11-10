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
# RS (10D) = 过去 10 日涨幅 / SPY 同期涨幅（倍数，1.0=同步大盘）
# RS (20D) = 过去 20 日涨幅 / SPY 同期涨幅（倍数，1.0=同步大盘）
# RS (10W) = 过去 50 日（10 周）涨幅 / SPY 同期涨幅（倍数）
# 量比 = 今日成交量 / 20 日均量（不含今日）
# RS评级 = O'Neil RS Rating，横截面 1-99 百分位（CAN SLIM 门槛 80）
# RS倍数 = (1+个股252日涨幅)/(1+SPY同期涨幅)，财富指数之比（1.0 = 与大盘同步）
# Weinstein阶段 = Weinstein 四阶段分析（1 筑底 / 2 上升 / 3 做顶 / 4 下跌）
_CSV_HEADERS = [
    "日期", "股票", "信号", "强度(1-5)", "触发原因", "参考止损", "持仓股数",
    "RS (10D)", "RS (20D)", "RS (10W)", "量比", "RS评级", "RS倍数", "Weinstein阶段",
]


def process_signals(
    queue: EventQueue,
    config: dict,
    strategy_id: str = "v1_wizard",
    watchlist_records: list[dict] | None = None,
) -> list[dict]:
    """
    从事件队列中取出所有 SIGNAL 事件，输出到控制台和 CSV。

    参数：
        queue:       事件队列
        config:      从 config.yaml 读取的配置
        strategy_id: 策略文件夹 ID（如 "v1_wizard"），决定 CSV 存储路径
        watchlist_records: 可选，watchlist 候选股（用于显示未来潜在买入信号）

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

    # ── 把 watchlist 候选股 (SignalEvent 列表) 也转为 record 并入 records ──
    if watchlist_records:
        for ev in watchlist_records:
            if hasattr(ev, "data") and hasattr(ev, "symbol"):
                records.append(_event_to_record(ev))

    if print_to_console:
        _print_table(records, watchlist_records=watchlist_records or [])

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
    rs_value_10d = event.data.get("rs_value_10d")    # 10D
    rs_value = event.data.get("rs_value")          # 20D
    rs_value_10w = event.data.get("rs_value_10w")  # 10W (50 交易日)
    vol_ratio = event.data.get("volume_ratio")
    rs_rating = event.data.get("rs_rating")      # O'Neil 1-99 百分位
    rs_ratio = event.data.get("rs_ratio")        # 财富指数之比 vs SPY
    stage = event.data.get("weinstein_stage")    # Weinstein 四阶段标签

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

    # RS / 量比显示
    rs_10d_str = (
        f"{float(rs_value_10d):.4f}" if isinstance(rs_value_10d, (int, float)) else "—"
    )
    rs_str = (
        f"{float(rs_value):.4f}" if isinstance(rs_value, (int, float)) else "—"
    )
    rs_10w_str = (
        f"{float(rs_value_10w):.4f}" if isinstance(rs_value_10w, (int, float)) else "—"
    )
    vol_str = (
        f"{float(vol_ratio):.1f}x" if isinstance(vol_ratio, (int, float)) else "—"
    )
    rating_str = f"{int(rs_rating)}" if isinstance(rs_rating, (int, float)) else "—"
    mult_str = (
        f"{float(rs_ratio):.4f}" if isinstance(rs_ratio, (int, float)) else "—"
    )
    stage_str = str(stage) if stage else "—"

    return {
        "日期": date_str,
        "股票": event.symbol,
        "信号": _DIRECTION_CN.get(direction, direction),
        "强度(1-5)": strength,
        "强度星级": stars,
        "触发原因": reason,
        "参考止损": stop_str,
        "持仓股数": shares_str,
        "RS (10D)": rs_10d_str,
        "RS (20D)": rs_str,
        "RS (10W)": rs_10w_str,
        "量比": vol_str,
        "RS评级": rating_str,
        "RS倍数": mult_str,
        "Weinstein阶段": stage_str,
    }


def _print_table(records: list[dict], watchlist_records: list[dict] | None = None) -> None:
    """把信号以表格形式打印到控制台。

    顺序：
        1. 【买入信号】 - 当前最优先（用户重视买入）
        2. 【未来潜在买入】 - watchlist 中可能是未来买入机会的股票
        3. 【出场信号】 - 已持仓股票出场信号
        4. 【做空信号】 - 做空信号（用户不太关注，但保留作为参考）
    """
    # 分组：买入、卖出、做空信号分开显示
    buy_records = [r for r in records if r["信号"] == "买入"]
    sell_records = [r for r in records if r["信号"] == "卖出"]
    short_records = [r for r in records if r["信号"] == "做空"]

    # 从 watchlist 中筛选未来潜在买入（reversal_extension / base_tightening）
    # 两种类型分别归类：
    #   A. 底部反弹 (Reversal Extension): 最近20个交易日内曾低于EMA20 ≥10% + 累计反弹≥10% + 当日反弹≥3%，等待 Wedge Pop 确认
    #   B. 形态收紧 (Base Tightening): 价格>EMA20 + 10日振幅<5%，等待 Base n' Break 突破
    reversal_extension_records: list[dict] = []
    base_tightening_records: list[dict] = []
    if watchlist_records:
        for r in watchlist_records:
            # 支持 SignalEvent 对象和 dict 两种格式
            if hasattr(r, "data"):
                # SignalEvent 对象
                rs_value = r.data.get("rs_value")
                rs_value_10d = r.data.get("rs_value_10d")
                rs_value_10w = r.data.get("rs_value_10w")
                vol_ratio = r.data.get("volume_ratio")
                rs_rating = r.data.get("rs_rating")
                rs_ratio = r.data.get("rs_ratio")
                rec_dict = {
                    "股票": getattr(r, "symbol", ""),
                    "触发原因": r.data.get("reason", ""),
                    "强度(1-5)": r.data.get("strength", 0),
                    "参考止损": r.data.get("stop_loss", "—"),
                    "日期": r.timestamp.strftime("%Y-%m-%d") if hasattr(r, "timestamp") else "",
                    "RS (10D)": f"{float(rs_value_10d):.4f}" if isinstance(rs_value_10d, (int, float)) else "—",
                    "RS (20D)": f"{float(rs_value):.4f}" if isinstance(rs_value, (int, float)) else "—",
                    "RS (10W)": f"{float(rs_value_10w):.4f}" if isinstance(rs_value_10w, (int, float)) else "—",
                    "量比": f"{float(vol_ratio):.1f}x" if isinstance(vol_ratio, (int, float)) else "—",
                    "RS评级": f"{int(rs_rating)}" if isinstance(rs_rating, (int, float)) else "—",
                    "RS倍数": f"{float(rs_ratio):.4f}" if isinstance(rs_ratio, (int, float)) else "—",
                    "Weinstein阶段": str(r.data.get("weinstein_stage")) if r.data.get("weinstein_stage") else "—",
                }
            else:
                # dict 格式
                rec_dict = r

            reason = rec_dict.get("触发原因", "")
            if "Reversal Extension" in reason:
                strength = rec_dict.get("强度(1-5)", 0)
                # 解析距离和反弹幅度
                import re as _re
                dist_m = _re.search(r'Current EMA20 distance:\s*([+-]?[\d.]+)%', reason)
                snap_m = _re.search(r'Cum rebound \(since bottom (\d+)d ago\):\s+\+?([\d.]+)%', reason)
                vol_m = _re.search(r'vol\s+([\d.]+)x', reason)
                rs_m = _re.search(r'\[RS\]\s*([+-]?[\d.]+)', reason)
                rs_10d_m = _re.search(r'\[RS-10D\]\s*([+-]?[\d.]+)', reason)
                rs_10w_m = _re.search(r'\[RS-10W\]\s*([+-]?[\d.]+)', reason)
                rating_m = _re.search(r'\[RS-Rating\]\s*(\d+)', reason)
                mult_m = _re.search(r'\[RS-Mult\]\s*([+-]?[\d.]+)', reason)
                stage_m = _re.search(r'\[Stage\]\s*([^|]+)$', reason.strip())
                reversal_extension_records.append({
                    "日期": rec_dict.get("日期", ""),
                    "股票": rec_dict["股票"],
                    "强度(1-5)": strength,
                    "强度星级": ("★" * int(strength) + "☆" * (5 - int(strength))) if strength else "—",
                    "距EMA20": f"{dist_m.group(1)}%" if dist_m else "—",
                    "反弹": f"+{snap_m.group(2)}%" if snap_m else "—",
                    "底部距今": f"{snap_m.group(1)}d" if snap_m else "—",
                    "量比": f"{vol_m.group(1)}x" if vol_m else rec_dict.get("量比", "—"),
                    "RS (10D)": f"{rs_10d_m.group(1)}" if rs_10d_m else rec_dict.get("RS (10D)", "—"),
                    "RS (20D)": f"{rs_m.group(1)}" if rs_m else rec_dict.get("RS (20D)", "—"),
                    "RS (10W)": f"{rs_10w_m.group(1)}" if rs_10w_m else rec_dict.get("RS (10W)", "—"),
                    "RS评级": f"{rating_m.group(1)}" if rating_m else rec_dict.get("RS评级", "—"),
                    "RS倍数": f"{mult_m.group(1)}" if mult_m else rec_dict.get("RS倍数", "—"),
                    "Weinstein阶段": stage_m.group(1).strip() if stage_m else rec_dict.get("Weinstein阶段", "—"),
                    "参考止损": rec_dict.get("参考止损", "—"),
                    "触发原因": reason,
                })
            elif "Base Tightening" in reason:
                strength = rec_dict.get("强度(1-5)", 0)
                base_tightening_records.append({
                    "日期": rec_dict.get("日期", ""),
                    "股票": rec_dict["股票"],
                    "强度(1-5)": strength,
                    "强度星级": ("★" * int(strength) + "☆" * (5 - int(strength))) if strength else "—",
                    "RS (10D)": rec_dict.get("RS (10D)", "—"),
                    "RS (20D)": rec_dict.get("RS (20D)", "—"),
                    "RS (10W)": rec_dict.get("RS (10W)", "—"),
                    "量比": rec_dict.get("量比", "—"),
                    "RS评级": rec_dict.get("RS评级", "—"),
                    "RS倍数": rec_dict.get("RS倍数", "—"),
                    "Weinstein阶段": rec_dict.get("Weinstein阶段", "—"),
                    "参考止损": rec_dict.get("参考止损", "—"),
                    "触发原因": reason,
                })

    future_buy_total = len(reversal_extension_records) + len(base_tightening_records)

    print()
    print("=" * 75)
    print("信号报告")
    print("=" * 75)

    if buy_records:
        print(f"\n【买入信号】共 {len(buy_records)} 个")
        print(f"{'日期':<12} {'股票':<8} {'强度':<8} {'RS10D':<8} {'RS20D':<8} {'RS10W':<8} {'量比':<8} {'RS评级':<7} {'RS倍数':<8} {'WStage':<12} {'参考止损':<10} 触发原因")
        print("-" * 137)
        for r in sorted(buy_records, key=lambda x: -x["强度(1-5)"]):
            print(
                f"{r['日期']:<12} {r['股票']:<8} {r['强度星级']:<8} "
                f"{r.get('RS (10D)', '—'):<8} {r.get('RS (20D)', '—'):<8} {r.get('RS (10W)', '—'):<8} {r.get('量比', '—'):<8} "
                f"{r.get('RS评级', '—'):<7} {r.get('RS倍数', '—'):<8} {r.get('Weinstein阶段', '—'):<12} "
                f"{r['参考止损']:<10} {r['触发原因']}"
            )

    if reversal_extension_records or base_tightening_records:
        print(f"\n【未来潜在买入】共 {future_buy_total} 个 (Pre-Buy Setups · 等待买入确认)")
        print("─" * 75)
        print("  逻辑：尚未触发【买入信号】，但已出现底部/形态特征，等待特定形态确认后转正。")
        print()

        if reversal_extension_records:
            print(f"  ▎类型 A — 底部反弹 (Reversal Extension) · 共 {len(reversal_extension_records)} 个")
            print("    触发条件：最近20个交易日内曾低于 EMA20 10% 以上 + 累计反弹 ≥10% + 当日反弹 ≥3%")
            print("    等待确认：出现 Wedge Pop 形态 → 转正为【买入信号】")
            print("    风控要点：若再次跌破 EMA20 × 0.95，形态失效")
            print()
            print(f"    {'日期':<12} {'股票':<8} {'强度':<8} {'距EMA20':<10} {'累计反弹':<10} {'底部距今':<10} {'量比':<7} {'RS10D':<8} {'RS20D':<8} {'RS10W':<8} {'RS评级':<7} {'RS倍数':<8} {'WStage':<12} {'参考止损':<10}")
            print("    " + "-" * 147)
            for r in sorted(reversal_extension_records, key=lambda x: float(x["距EMA20"].rstrip("%"))):
                print(
                    f"    {r['日期']:<12} {r['股票']:<8} {r['强度星级']:<8} "
                    f"{r['距EMA20']:<10} {r['反弹']:<10} {r['底部距今']:<10} {r['量比']:<7} "
                    f"{r.get('RS (10D)', '—'):<8} {r.get('RS (20D)', '—'):<8} {r.get('RS (10W)', '—'):<8} "
                    f"{r.get('RS评级', '—'):<7} {r.get('RS倍数', '—'):<8} {r.get('Weinstein阶段', '—'):<12} {r['参考止损']:<10}"
                )
            print()

        if base_tightening_records:
            print(f"  ▎类型 B — 形态收紧 (Base Tightening) · 共 {len(base_tightening_records)} 个")
            print("    触发条件：价格 > EMA20 + EMA10 > EMA20（多头排列） + 10日振幅 < 7%")
            print("    等待确认：放量突破 20日高点 → 转正为【买入信号】(Base n' Break)")
            print("    风控要点：跌破 EMA20 视为形态失败")
            print()
            print(f"    {'日期':<12} {'股票':<8} {'强度':<8} {'RS10D':<8} {'RS20D':<8} {'RS10W':<8} {'量比':<8} {'RS评级':<7} {'RS倍数':<8} {'WStage':<12} {'参考止损':<10} 触发原因")
            print("    " + "-" * 137)
            for r in base_tightening_records:
                print(
                    f"    {r['日期']:<12} {r['股票']:<8} {r['强度星级']:<8} "
                    f"{r.get('RS (10D)', '—'):<8} {r.get('RS (20D)', '—'):<8} {r.get('RS (10W)', '—'):<8} {r.get('量比', '—'):<8} "
                    f"{r.get('RS评级', '—'):<7} {r.get('RS倍数', '—'):<8} {r.get('Weinstein阶段', '—'):<12} "
                    f"{r['参考止损']:<10} {r['触发原因']}"
                )
            print()

    if sell_records:
        print(f"\n【出场信号】共 {len(sell_records)} 个")
        print(f"{'日期':<12} {'股票':<8} {'持仓股数':<14} 原因")
        print("-" * 75)
        for r in sell_records:
            print(f"{r['日期']:<12} {r['股票']:<8} {r['持仓股数']:<14} {r['触发原因']}")

    if short_records:
        print(f"\n【做空信号】共 {len(short_records)} 个")
        print(f"{'日期':<12} {'股票':<8} {'强度':<8} {'RS10D':<8} {'RS20D':<8} {'RS10W':<8} {'量比':<8} {'RS评级':<7} {'RS倍数':<8} {'WStage':<12} {'参考止损':<10} 触发原因")
        print("-" * 137)
        for r in sorted(short_records, key=lambda x: -x["强度(1-5)"]):
            print(
                f"{r['日期']:<12} {r['股票']:<8} {r['强度星级']:<8} "
                f"{r.get('RS (10D)', '—'):<8} {r.get('RS (20D)', '—'):<8} {r.get('RS (10W)', '—'):<8} {r.get('量比', '—'):<8} "
                f"{r.get('RS评级', '—'):<7} {r.get('RS倍数', '—'):<8} {r.get('Weinstein阶段', '—'):<12} "
                f"{r['参考止损']:<10} {r['触发原因']}"
            )

    if not buy_records and not sell_records and not short_records and not reversal_extension_records and not base_tightening_records:
        print("\n今日无有效信号")

    print("=" * 75)
    print()


def _append_to_csv(records: list[dict], strategy_id: str = "v1_wizard") -> None:
    """把信号追加写入 CSV 文件（去重后写入，同一日同一股票同一方向只保留一条）。

    Schema 迁移：旧 7/9/10/11/13 列 schema 升级到 14 列（新增 RS评级、RS倍数、Weinstein阶段），旧文件先备份再重写。
    """
    strategy_dir = OUTPUT_DIR / strategy_id
    strategy_dir.mkdir(parents=True, exist_ok=True)
    signals_csv = strategy_dir / "signals.csv"

    # Schema 迁移：检测旧 schema，备份后升级为新 14 列
    if signals_csv.exists():
        with open(signals_csv, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                header = []
        # 旧 schema：缺 "Weinstein阶段" 的都是旧版
        # 新 schema：14 列（含 "Weinstein阶段"）
        needs_migration = (
            len(header) > 0 and "Weinstein阶段" not in header
        )
        if needs_migration:
            from datetime import datetime as _dt
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            backup_path = signals_csv.with_name(f"signals.csv.bak.{ts}")
            try:
                signals_csv.rename(backup_path)
                print(f"[CSV迁移] 备份旧 schema ({len(header)} 列) → {backup_path}")
                # 读取旧数据，扩展到 14 列（缺列填 '—'），覆写为新 schema
                with open(backup_path, "r", newline="", encoding="utf-8-sig") as src, \
                     open(signals_csv, "w", newline="", encoding="utf-8-sig") as dst:
                    src_reader = csv.DictReader(src)
                    new_fieldnames = _CSV_HEADERS
                    dst_writer = csv.DictWriter(
                        dst, fieldnames=new_fieldnames, extrasaction="ignore"
                    )
                    dst_writer.writeheader()
                    for row in src_reader:
                        # 兼容老 key → 新 key：旧 "RS" 列映射到 "RS (20D)"
                        if "RS" in row and "RS (20D)" not in row:
                            row["RS (20D)"] = row.pop("RS")
                        # 缺的新字段填 "—"
                        for col in new_fieldnames:
                            row.setdefault(col, "—")
                        dst_writer.writerow({col: row.get(col, "—") for col in new_fieldnames})
                print(f"[CSV迁移] 已用新 {len(_CSV_HEADERS)} 列 schema 覆写 {signals_csv}")
            except Exception as e:
                # 迁移失败，恢复原文件不阻塞写入
                print(f"[CSV迁移] 备份/迁移失败：{e} — 回退到旧路径")
                if backup_path.exists() and not signals_csv.exists():
                    backup_path.rename(signals_csv)

    # 读取已有记录，建立去重 key 集合
    existing_keys: set[tuple] = set()
    if signals_csv.exists():
        with open(signals_csv, "r", newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_keys.add((row.get("日期"), row.get("股票"), row.get("信号")))

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
                "RS (10D)": r.get("RS (10D)", "—"),
                "RS (20D)": r.get("RS (20D)", "—"),
                "RS (10W)": r.get("RS (10W)", "—"),
                "量比": r.get("量比", "—"),
                "RS评级": r.get("RS评级", "—"),
                "RS倍数": r.get("RS倍数", "—"),
                "Weinstein阶段": r.get("Weinstein阶段", "—"),
            })

    print(f"[输出] 信号已保存到 {signals_csv}（写入 {len(new_records)} 条新记录，去重 {len(records) - len(new_records)} 条）")
