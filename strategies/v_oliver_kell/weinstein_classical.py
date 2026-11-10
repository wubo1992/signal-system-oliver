"""
strategies/v_oliver_kell/weinstein_classical.py — Weinstein 四阶段经典结构引擎

移植自 `/Users/wubo/Desktop/codes/Stan Weinstein stage analysis/weinstein/classical.py`
（规则版本 WEINSTEIN-STRUCTURE-1.3），规范见该项目的 `docs/CLASSICAL_METHODOLOGY.md`。

与本项目早先那套「日线 MA30/MA150/MA200 + 斜率」的临时判断不同，这里采用
Weinstein 原书口径的核心：**周线 + 30 周简单移动平均线**。

主阶段只使用：
    - 30 周均线斜率（当前 30W SMA 相对 4 周前的变化率，±0.30% 为走平测量参考）
    - 价格相对 30 周均线的位置
    - 前 26 周区间支撑阻力（不含当前周）
    - 最近 4 周与此前 4 周的高低点结构（更高低点 / 更低高点 / 更低低点）
    - 前序阶段上下文（区分筑底与顶部、底部失败、顶部向上突破、V 形过渡）

明确**不**用于阶段判定：
    - 13 周动量分数（仅作为辅助价格信息）
    - 连续三周确认、固定八周最短阶段
    - -8% 偏离 + -5% 动量的自动跳级
    - 用规则一致性分数反推阶段

Stage 1 的两条硬规则（来自原项目）：
    - 只有突破**自身底部阻力**才进入 Stage 2
    - 只有跌破**自身底部支撑**才退回 Stage 4

子阶段（GTA A/B）完整实现：1A/1/1B、2A/2/2B、3A/3/3B、4A/4/4B/4B-。
"""

from datetime import date, datetime

# ── 常量 ───────────────────────────────────────────────────
MA_WINDOW = 30          # 30 周简单移动平均线
SLOPE_LOOKBACK = 4      # 均线斜率回看周数
FLAT_SLOPE = 0.003      # ±0.30% 视为走平（工程测量参考）
RANGE_LOOKBACK = 26     # 前 26 周区间
MIN_WEEKLY_BARS = 60    # 至少需要 60 根周线
RULES_VERSION = "WEINSTEIN-STRUCTURE-1.3"

STAGE_LABELS = {1: "Stage 1 筑底", 2: "Stage 2 上升", 3: "Stage 3 做顶", 4: "Stage 4 下跌"}
STAGE_NAMES = {1: "筑底期", 2: "上升期", 3: "顶部期", 4: "下跌期"}
STAGE_DESCRIPTIONS = {
    1: "下跌后价格尝试围绕 30 周均线构建底部。",
    2: "价格主要运行在上升的 30 周均线上方。",
    3: "上涨后价格停止持续推进，进入顶部构建或过渡。",
    4: "价格主要运行在下降的 30 周均线下方。",
}
SUBSTAGE_NAMES = {
    "1A": "筑底初期", "1": "筑底期", "1B": "筑底后期",
    "2A": "上升初期", "2": "上升期", "2B": "上升后期",
    "3A": "顶部初期", "3": "顶部期", "3B": "顶部后期",
    "4A": "下跌初期", "4": "下跌期", "4B": "下跌后期", "4B-": "周期低点观察",
}
SUBSTAGE_DESCRIPTIONS = {
    "1A": "底部开始形成，仍需要更多时间确认，不宜把初步止跌直接当成完成筑底。",
    "1": "处于底部构建阶段，价格与均线逐步平衡，继续观察区间和突破条件。",
    "1B": "底部构建后期，价格接近区间阻力且动量改善，重点观察是否形成有效突破。",
    "2A": "处于上升趋势早期，通常对应底部突破或首次延续确认；突破质量仍需成交量和相对强度验证。",
    "2": "处于已确立的上升趋势，价格与均线结构保持健康。",
    "2B": "处于上升趋势后期或动能减速区，应关注整理、失败突破和均线走平风险。",
    "3A": "顶部开始形成，上涨结构减弱，但尚未出现严重区间破位。",
    "3": "处于明确的顶部整理区域，价格与均线结构显示上涨已停止持续推进。",
    "3B": "顶部特征日益明显，价格、动量或区间支撑进一步恶化，属于顶部后期/破位过渡。",
    "4A": "已进入下跌趋势初期，顶部支撑和价格结构开始明确失守。",
    "4": "处于已确立的下跌趋势，价格和均线结构持续偏弱。",
    "4B": "处于下跌趋势后期，但后期不等于见底，仍需要底部结构确认。",
    "4B-": "尚未正式进入 Stage 1A，但出现本轮周期低点可能形成的观察信号，不等于反转确认。",
}


# ── 基础工具 ───────────────────────────────────────────────
def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _rounded(value, digits: int = 2):
    return round(value, digits) if value is not None else None


def _structure_direction(slope: float, distance: float) -> str:
    if slope > FLAT_SLOPE and distance > 0:
        return "up"
    if slope < -FLAT_SLOPE and distance < 0:
        return "down"
    if abs(slope) <= FLAT_SLOPE:
        return "flat"
    return "mixed"


def is_developing_week(latest_date: str, today: date) -> bool:
    """当前 ISO 周尚未走完时，最新周线属于「发展中」判断。"""
    latest = date.fromisoformat(latest_date)
    if latest.isocalendar()[:2] != today.isocalendar()[:2]:
        return False
    return today.weekday() < 5


# ── 子阶段判定 ─────────────────────────────────────────────
def classify_classical_substage(week: dict) -> tuple[str, str]:
    """用结构（而非动量分数）映射 Weinstein GTA 的 A/B 子阶段。"""
    stage = week["stage"]
    age = week["weeks_in_stage"]
    slope = week["ma30_slope"] or 0
    distance = week["price_vs_ma"] or 0
    slope_delta = week["slope_delta_4w"] or 0
    range_position = week["range_position_26w"]

    if stage == 1:
        if week["breakout_26w"] or (
            age >= 8 and range_position is not None and range_position >= 0.75
            and slope >= -FLAT_SLOPE and week["higher_lows"]
        ):
            return "1B", "底部区间较成熟，价格接近/突破既有阻力且低点改善，符合 Stage 1B。"
        if age <= 4 or slope < -FLAT_SLOPE or week["new_low_13w"]:
            return "1A", "底部仍早期、均线仍下降或价格继续创新低，需要更多时间形成结构。"
        return "1", "已经形成可识别的底部区间，但尚未达到 Stage 1B 的成熟突破条件。"

    if stage == 2:
        if (
            week["lower_highs"]
            or (age >= 16 and slope_delta <= -FLAT_SLOPE)
            or (age >= 26 and week["direction"] in ("flat", "mixed"))
        ):
            return "2B", "上升均线仍未逆转，但出现更低高点、整理或均线增速放缓，符合 Stage 2B 后期观察。"
        if (
            age <= 8 and week["previous_stage"] == 1
            and week["breakout_in_stage"] and not week["continuation_in_stage"]
            and week["direction"] in ("up", "flat", "mixed")
        ):
            return "2A", "本阶段发生真实底部突破，且尚未进入首次延续上涨，属于 Stage 2A 突破/首次回踩区。"
        return "2", "价格仍位于上升均线之上，且已进入或处于延续上涨结构，归为 Stage 2。"

    if stage == 3:
        if (
            week["breakdown_26w"]
            or (slope < -FLAT_SLOPE and distance < 0)
            or (week["lower_highs"] and distance < 0)
            or (week["lower_lows"] and distance < 0)
            or (week["tests_support"] and week["lower_highs"])
        ):
            return "3B", "出现更低高点/更低低点并跌破均线，或测试、跌破顶部支撑，顶部结构持续恶化，符合 Stage 3B。"
        if age <= 4:
            if week.get("stage3_matured"):
                return "3", "本段顶部已经历破位或成熟整理；当前属于 Stage 3 顶部区域恢复，不能倒退为 Stage 3A。"
            return "3A", "上涨后顶部开始形成，但支撑尚未明确失守，属于 Stage 3A。"
        return "3", "已经形成顶部整理结构，尚未出现足够的 Stage 3B 支撑失守证据。"

    if (
        week["direction"] == "up"
        or (distance > 0 and week["higher_lows"])
        or (age >= 4 and week["rebound_from_stage_low"] >= 0.10 and not week["new_low_13w"])
    ):
        return "4B-", "价格从阶段低点反弹或重新站回均线，进入 4B- 低点观察；尚不等于 Stage 1A。"
    if age >= 26 or (
        age >= 16
        and (slope_delta > 0 or (week["volume_ratio"] is not None and week["volume_ratio"] < 0.8) or distance <= -0.15)
    ):
        return "4B", "下跌趋势已充分延展并出现降速、缩量或深度偏离，归为 Stage 4B，仍不提前猜底。"
    if age <= 8:
        return "4A", "顶部或底部支撑失守后的下跌初期，符合 Stage 4A。"
    return "4", "下降趋势已经确立，尚未出现充分的后期降速或低点观察证据。"


# ── 主阶段状态机 ───────────────────────────────────────────
def _assign_classical_stages(weeks: list[dict], valid_indices: list[int]) -> list[int]:
    """经典结构主阶段状态机（含底部自身支撑/阻力的突破与失守规则）。"""
    stages = []
    current = None
    base_resistance = base_support = None
    for index in valid_indices:
        week = weeks[index]
        slope = week["ma30_slope"] or 0
        distance = week["price_vs_ma"] or 0
        direction = week["direction"]
        close = week.get("close")
        breakout_base = base_resistance is not None and close is not None and close > base_resistance
        breakdown_base = base_support is not None and close is not None and close < base_support
        week.update({
            "base_resistance": base_resistance, "base_support": base_support,
            "breakout_base": breakout_base, "breakdown_base": breakdown_base,
        })
        if current is None:
            if direction == "up":
                current = 2
            elif direction == "down":
                current = 4
            else:
                current = 3 if (week["change_26w"] or 0) > 0 else 1
        elif current == 1:
            if direction == "up" and breakout_base:
                current = 2
            elif direction == "down" and breakdown_base:
                # 失败以底部自身支撑为准，而不是更低的四周低点或跌破长期均线
                current = 4
        elif current == 2:
            if direction == "down" and (week["breakdown_26w"] or week["new_low_13w"] or week["lower_lows"]):
                current = 4
            elif distance < 0 and (week["lower_highs"] or week["lower_lows"] or slope <= FLAT_SLOPE):
                current = 3
            elif abs(slope) <= FLAT_SLOPE and week["ma_crosses_13w"] >= 2:
                current = 3
        elif current == 3:
            if direction == "down" and (week["breakdown_26w"] or week["new_low_13w"] or week["lower_lows"]):
                current = 4
            elif direction == "up" and week["breakout_26w"]:
                current = 2
        elif current == 4:
            if direction == "up" and week["breakout_26w"]:
                current = 2
            elif distance > 0 and (week["higher_lows"] or abs(slope) <= FLAT_SLOPE):
                current = 1
            elif abs(slope) <= FLAT_SLOPE and week["higher_lows"]:
                current = 1
        stages.append(current)
        if current == 1:
            high, low = week.get("high"), week.get("low")
            if high is not None:
                base_resistance = high if base_resistance is None else max(base_resistance, high)
            if low is not None:
                base_support = low if base_support is None else min(base_support, low)
        else:
            base_resistance = base_support = None
    return stages


# ── 分析主体 ───────────────────────────────────────────────
def analyze_classical(bars: list[dict], as_of: date | None = None) -> dict:
    """对周线序列做经典 Weinstein 结构分析。

    参数：
        bars: [{"date": "YYYY-MM-DD", "open", "high", "low", "close", "volume"}, ...]（按时间升序）
        as_of: 判断「发展中」周线时使用的当前日期

    返回：summary / weeks / segments 等，summary 内含 stage、substage 与各项结构读数。
    """
    if len(bars) < MIN_WEEKLY_BARS:
        raise ValueError(f"至少需要 {MIN_WEEKLY_BARS} 根周线，当前只有 {len(bars)} 根")

    closes = [bar["close"] for bar in bars]
    volumes = [bar["volume"] for bar in bars]
    valid_offset = MA_WINDOW - 1 + SLOPE_LOOKBACK
    weeks: list[dict] = []
    valid_indices: list[int] = []

    for index, bar in enumerate(bars):
        ma30 = _mean(closes[index - MA_WINDOW + 1:index + 1]) if index >= MA_WINDOW - 1 else None
        slope = distance = None
        if index >= valid_offset and ma30:
            previous_ma = _mean(closes[index - SLOPE_LOOKBACK - MA_WINDOW + 1:index - SLOPE_LOOKBACK + 1])
            slope = ma30 / previous_ma - 1 if previous_ma else 0
            distance = bar["close"] / ma30 - 1
            valid_indices.append(index)

        resistance = support = range_position = None
        breakout = breakdown = False
        if index >= RANGE_LOOKBACK:
            prior = bars[index - RANGE_LOOKBACK:index]
            resistance = max(item["high"] for item in prior)
            support = min(item["low"] for item in prior)
            breakout = bar["close"] > resistance
            breakdown = bar["close"] < support
            range_position = (bar["close"] - support) / (resistance - support) if resistance > support else 0.5

        lower_highs = higher_lows = lower_lows = False
        if index >= 8:
            recent = bars[index - 3:index + 1]
            previous = bars[index - 7:index - 3]
            lower_highs = max(item["high"] for item in recent) < max(item["high"] for item in previous)
            higher_lows = min(item["low"] for item in recent) > min(item["low"] for item in previous)
            lower_lows = min(item["low"] for item in recent) < min(item["low"] for item in previous)

        new_low = index >= 13 and bar["close"] < min(closes[index - 13:index])
        new_high = index >= 13 and bar["close"] > max(closes[index - 13:index])

        crosses = 0
        if index >= valid_offset + 13:
            signs = [1 if (weeks[j]["price_vs_ma"] or 0) > 0 else -1 for j in range(index - 12, index)]
            previous_sign = signs[0]
            for sign in signs[1:]:
                if sign != previous_sign:
                    crosses += 1
                previous_sign = sign

        volume_ratio = None
        if index >= 20:
            average = _mean(volumes[index - 20:index])
            volume_ratio = bar["volume"] / average if average else None

        slope_delta = None
        if index >= valid_offset + SLOPE_LOOKBACK:
            prior_slope = weeks[index - SLOPE_LOOKBACK]["ma30_slope"]
            slope_delta = slope - prior_slope if prior_slope is not None else None

        momentum = bar["close"] / closes[index - 13] - 1 if index >= 13 else None
        direction = _structure_direction(slope or 0, distance or 0) if slope is not None else None

        weeks.append({
            "date": bar["date"],
            "open": _rounded(bar.get("open")), "high": _rounded(bar.get("high")),
            "low": _rounded(bar.get("low")), "close": _rounded(bar.get("close")),
            "volume": _rounded(bar.get("volume"), 0), "ma30": _rounded(ma30, 3),
            "ma30_slope_pct": _rounded(slope * 100 if slope is not None else None, 3),
            "price_vs_ma_pct": _rounded(distance * 100 if distance is not None else None),
            "momentum_13w_pct": _rounded(momentum * 100 if momentum is not None else None),
            "volume_ratio": _rounded(volume_ratio), "direction": direction, "signal_score": None, "stage": None,
            "ma30_slope": slope, "price_vs_ma": distance, "momentum_13w": momentum,
            "slope_delta_4w": slope_delta, "range_position_26w": range_position,
            "resistance_26w": _rounded(resistance), "support_26w": _rounded(support),
            "breakout_26w": breakout, "breakdown_26w": breakdown,
            "new_low_13w": new_low, "new_high_13w": new_high,
            "lower_highs": lower_highs, "higher_lows": higher_lows, "lower_lows": lower_lows,
            "tests_support": support is not None and bar["close"] >= support and bar["close"] <= support * 1.03,
            "ma_crosses_13w": crosses,
            "change_26w": bar["close"] / closes[index - RANGE_LOOKBACK] - 1 if index >= RANGE_LOOKBACK else None,
            "severe_breakdown": False, "rebound_from_stage_low": 0.0,
        })

    stages = _assign_classical_stages(weeks, valid_indices)

    active_stage = previous_stage = active_substage = None
    stage_age = substage_age = 0
    stage_low = None
    breakout_in_stage = continuation_in_stage = False
    stage3_matured = False
    breakout_close = None
    for index, stage in zip(valid_indices, stages):
        week = weeks[index]
        if stage != active_stage:
            if active_stage is not None:
                previous_stage = active_stage
            active_stage = stage
            stage_age = 0
            stage_low = week["close"]
            active_substage = None
            breakout_in_stage = continuation_in_stage = False
            stage3_matured = False
            breakout_close = None
        stage_age += 1
        if (week["breakout_26w"] or week.get("breakout_base")) and not breakout_in_stage:
            breakout_in_stage = True
            breakout_close = week["close"]
        elif breakout_in_stage and not continuation_in_stage and week["new_high_13w"] and breakout_close is not None and week["close"] > breakout_close:
            continuation_in_stage = True
        stage_low = min(stage_low, week["close"])
        week.update({
            "stage": stage, "stage_name": STAGE_NAMES[stage], "weeks_in_stage": stage_age,
            "previous_stage": previous_stage, "breakout_in_stage": breakout_in_stage,
            "continuation_in_stage": continuation_in_stage,
            "rebound_from_stage_low": week["close"] / stage_low - 1 if stage_low else 0,
        })
        week["stage3_matured"] = stage3_matured
        substage, reason = classify_classical_substage(week)
        if stage == 3 and substage in ("3", "3B"):
            stage3_matured = True
        substage_age = substage_age + 1 if substage == active_substage else 1
        active_substage = substage
        week.update({
            "substage": substage, "substage_name": SUBSTAGE_NAMES[substage],
            "substage_reason": reason, "weeks_in_substage": substage_age,
        })

    segments = _build_segments(weeks, valid_offset)
    substage_segments = _build_segments(weeks, valid_offset, key="substage")

    latest = weeks[-1]
    developing = is_developing_week(latest["date"], as_of or date.today())
    latest["is_developing"] = developing
    segments[-1]["is_developing"] = developing
    substage_segments[-1]["is_developing"] = developing
    confirmed = weeks[-2] if developing else latest

    return {
        "summary": {
            "stage": latest["stage"],
            "stage_name": STAGE_NAMES[latest["stage"]],
            "stage_label": STAGE_LABELS[latest["stage"]],
            "substage": latest["substage"],
            "substage_name": SUBSTAGE_NAMES[latest["substage"]],
            "substage_reason": latest["substage_reason"],
            "substage_label": f"{latest['substage']} {SUBSTAGE_NAMES[latest['substage']]}",
            "latest_direction": latest["direction"],
            "since": segments[-1]["start_date"],
            "duration_weeks": segments[-1]["weeks"],
            "substage_since": substage_segments[-1]["start_date"],
            "substage_duration_weeks": substage_segments[-1]["weeks"],
            "consistency": _fit(latest),
            "is_developing": developing,
            "week_status": "developing" if developing else "confirmed",
            "confirmed": {
                "date": confirmed["date"], "stage": confirmed["stage"],
                "stage_name": STAGE_NAMES[confirmed["stage"]],
                "substage": confirmed["substage"],
                "substage_name": SUBSTAGE_NAMES[confirmed["substage"]],
                "close": confirmed["close"], "ma30": confirmed["ma30"],
            },
            "close": latest["close"], "ma30": latest["ma30"],
            "ma30_slope_pct": latest["ma30_slope_pct"],
            "price_vs_ma_pct": latest["price_vs_ma_pct"],
            "momentum_13w_pct": latest["momentum_13w_pct"],
            "volume_ratio": latest["volume_ratio"],
            "signal_score": None,
            "reasons": _reasons(latest, developing),
        },
        "weeks": weeks, "segments": segments, "substage_segments": substage_segments,
        "method": {
            "rules_version": RULES_VERSION, "model": "weekly_30w_structure",
            "ma_window": MA_WINDOW, "slope_lookback": SLOPE_LOOKBACK,
            "flat_slope_pct": FLAT_SLOPE * 100, "range_lookback": RANGE_LOOKBACK,
            "uses_momentum_for_stage": False, "uses_fixed_confirmation_weeks": False,
            "uses_severe_percentage_stage_jump": False,
        },
    }


def _fit(week: dict) -> int:
    """规则契合度（不是概率）。"""
    stage = week["stage"]
    slope = week["ma30_slope"] or 0
    distance = week["price_vs_ma"] or 0
    if stage == 2:
        checks = [slope > FLAT_SLOPE, distance > 0, not week["breakdown_26w"], not week["lower_lows"]]
    elif stage == 4:
        checks = [slope < -FLAT_SLOPE, distance < 0, not week["breakout_26w"], not week["higher_lows"]]
    else:
        checks = [
            week["previous_stage"] is not None,
            week["range_position_26w"] is not None,
            not week["breakdown_26w"],
            week["direction"] in ("flat", "mixed"),
        ]
    return min(95, round(45 + 50 * sum(checks) / 4))


def _reasons(week: dict, developing: bool) -> list[str]:
    slope = week["ma30_slope_pct"]
    distance = week["price_vs_ma_pct"]
    momentum = week["momentum_13w_pct"]
    structure = []
    if week["lower_highs"]:
        structure.append("更低高点")
    if week["higher_lows"]:
        structure.append("更高低点")
    if week["lower_lows"]:
        structure.append("更低低点")
    if week["new_low_13w"]:
        structure.append("13周新低")
    range_position = week["range_position_26w"]
    position_text = "数据不足" if range_position is None else f"{range_position * 100:.1f}%"
    return [
        f"30 周均线近 4 周变化 {slope:+.2f}%，价格相对 30 周均线 {distance:+.2f}%，13 周动量 {momentum:+.2f}%（仅参考）。",
        "高低点结构：" + ("、".join(structure) if structure else "未形成显著新结构") + "。",
        f"26 周区间：支撑 {week['support_26w']} · 阻力 {week['resistance_26w']} · 位置 {position_text}。",
        week["substage_reason"],
        ("最新周线尚未完成，当前为发展中判断。" if developing else "最新周线为确认读数。"),
    ]


def _build_segments(weeks: list[dict], valid_offset: int, key: str = "stage") -> list[dict]:
    valid = weeks[valid_offset:]
    if not valid:
        return []
    segments = []
    start = 0
    for index in range(1, len(valid) + 1):
        if index < len(valid) and valid[index][key] == valid[start][key]:
            continue
        first, last = valid[start], valid[index - 1]
        baseline_price = valid[start - 1]["close"] if start > 0 else first["close"]
        name_key = "stage_name" if key == "stage" else "substage_name"
        segment = {
            "stage": first["stage"],
            key: first[key],
            "name": first[name_key],
            "start_date": first["date"],
            "end_date": last["date"],
            "weeks": index - start,
            "start_price": first["close"],
            "baseline_price": baseline_price,
            "end_price": last["close"],
            "return_pct": _rounded((last["close"] / baseline_price - 1) * 100),
        }
        if key == "substage":
            segment["substage_name"] = first["substage_name"]
        segments.append(segment)
        start = index
    return segments


# ── 对外：日线 DataFrame → 周线 → 阶段判定 ──────────────────
def daily_to_weekly_bars(df) -> list[dict]:
    """把日线 DataFrame（index 为日期）重采样成周线（W-FRI）K 线列表。

    返回按时间升序的 [{"date", "open", "high", "low", "close", "volume"}]。
    """
    import pandas as pd

    if df is None or df.empty:
        return []
    frame = df.copy()
    if not isinstance(frame.index, pd.DatetimeIndex):
        frame.index = pd.to_datetime(frame.index)
    if frame.index.tzinfo is None:
        frame.index = frame.index.tz_localize("UTC")
    if "close" not in frame.columns:
        return []
    agg = {}
    if "open" in frame.columns:
        agg["open"] = "first"
    if "high" in frame.columns:
        agg["high"] = "max"
    if "low" in frame.columns:
        agg["low"] = "min"
    agg["close"] = "last"
    if "volume" in frame.columns:
        agg["volume"] = "sum"
    weekly = frame.resample("W-FRI").agg(agg)
    weekly = weekly.dropna(subset=["close"])
    bars = []
    for stamp, row in weekly.iterrows():
        bars.append({
            "date": stamp.date().isoformat(),
            "open": float(row.get("open", row["close"])) if row.get("open") is not None else float(row["close"]),
            "high": float(row["high"]) if row.get("high") is not None else float(row["close"]),
            "low": float(row["low"]) if row.get("low") is not None else float(row["close"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if row.get("volume") is not None else 0.0,
        })
    return bars


def analyze_daily(df, as_of: date | None = None) -> dict | None:
    """日线 → 周线 → 经典 Weinstein 分析。数据不足返回 None。"""
    bars = daily_to_weekly_bars(df)
    if len(bars) < MIN_WEEKLY_BARS:
        return None
    try:
        return analyze_classical(bars, as_of=as_of)
    except Exception:
        return None


def stage_label(stage: int | None, substage: str | None = None) -> str:
    """阶段标签：'Stage 2 上升 · 2B 上升后期'。"""
    if stage is None:
        return "—"
    base = STAGE_LABELS.get(stage, f"Stage {stage}")
    if substage:
        return f"{base} · {substage} {SUBSTAGE_NAMES.get(substage, '')}".strip()
    return base
