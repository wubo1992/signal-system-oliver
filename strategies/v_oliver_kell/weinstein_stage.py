"""
strategies/v_oliver_kell/weinstein_stage.py — Weinstein 四阶段分析（Stage Analysis）

Stan Weinstein《Secrets for Profiting in Bull and Bear Markets》的核心框架：
把个股生命周期切成四个阶段，判断当前处于哪一段。

    Stage 1 筑底（Basing）    — 下跌后形成底部区间，停止创新低，均线走平或价格重新站上均线
    Stage 2 上升（Markup）    — 价格运行在上升的 30 周均线上方
    Stage 3 做顶（Topping）   — 上涨后顶部结构形成：均线走平反复穿越，或更低高点并跌破均线
    Stage 4 下跌（Decline）   — 价格运行在下降的 30 周均线下方，更低低点或支撑失守

## 判定口径

采用 **周线 + 30 周简单移动平均线** 的经典结构引擎
（规则版本 WEINSTEIN-STRUCTURE-1.3，移植自
`/Users/wubo/Desktop/codes/Stan Weinstein stage analysis/weinstein/classical.py`）：

    - 30 周均线斜率（当前相对 4 周前的变化率，±0.30% 为走平参考）
    - 价格相对 30 周均线的位置
    - 前 26 周区间支撑阻力（不含当前周）
    - 最近 4 周与此前 4 周的高低点结构（更高低点 / 更低高点 / 更低低点）
    - 前序阶段上下文（区分筑底与顶部、底部失败、顶部向上突破、V 形过渡）

Stage 1 的两条硬规则：只有突破**自身底部阻力**才进入 Stage 2，
只有跌破**自身底部支撑**才退回 Stage 4。

同时输出完整 GTA A/B 子阶段：1A/1/1B、2A/2/2B、3A/3/3B、4A/4/4B/4B-。

## 与 Oliver Kell 六阶段的关系

两者不冲突，观察角度不同：
    - Kell 六阶段看**短期价格行为**（楔形、突破、回踩），决定「今天动不动手」
    - Weinstein 四阶段看**中长期趋势位置**，决定「这只票现在该不该碰」

典型组合：Stage 2 + Wedge Pop = 最强买点；Stage 4 + 任何买入信号 = 逆势，需降权；
Stage 1 + Base Tightening = 筑底观察期，突破后有望进 Stage 2。

## 数据要求

至少需要 60 根周线（约 300 个交易日）；不足时返回 None，输出显示为「—」。
新股 / 上市时间太短的股票无法判定阶段，这是方法的固有限制，不做插值猜测。
"""

from datetime import date, datetime

import pandas as pd

from strategies.v_oliver_kell.weinstein_classical import (  # noqa: F401
    MIN_WEEKLY_BARS,
    RULES_VERSION,
    STAGE_LABELS,
    SUBSTAGE_NAMES,
    analyze_daily,
    stage_label as _classical_stage_label,
)

__all__ = [
    "STAGE_LABELS",
    "MIN_WEEKLY_BARS",
    "RULES_VERSION",
    "compute_weinstein_stage",
    "compute_weinstein_detail",
    "stage_label",
]


def _as_of_date(as_of) -> date | None:
    """把 datetime / date 统一成 date（用于判断「发展中」周线）。"""
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        return as_of.date()
    if isinstance(as_of, date):
        return as_of
    return None


def compute_weinstein_detail(df: pd.DataFrame | None, as_of=None) -> dict | None:
    """
    计算单只股票的 Weinstein 阶段详情（主阶段 + 子阶段 + 结构读数）。

    参数：
        df: 含 open/high/low/close/volume 列的日线行情（升序，最后一根为当前时点）
        as_of: 当前日期（datetime 或 date），用于判断最新周线是否「发展中」

    返回：
        dict，含 stage / substage / label / slope / distance / reasons 等；
        数据不足（周线 < 60 根）时返回 None
    """
    if df is None or df.empty or "close" not in df.columns:
        return None
    result = analyze_daily(df, as_of=_as_of_date(as_of))
    if result is None:
        return None
    summary = result["summary"]
    summary["label"] = _classical_stage_label(summary["stage"], summary["substage"])
    summary["short_label"] = f"{STAGE_LABELS.get(summary['stage'], '—')} · {summary['substage']}"
    summary["rules_version"] = RULES_VERSION
    confirmed = summary.get("confirmed") or {}
    if confirmed:
        summary["confirmed_label"] = _classical_stage_label(
            confirmed.get("stage"), confirmed.get("substage"))
        summary["confirmed_date"] = confirmed.get("date")
    return summary


def compute_weinstein_stage(df: pd.DataFrame | None, as_of=None) -> tuple[int | None, str]:
    """
    计算单只股票的 Weinstein 阶段。

    参数：
        df: 含 close 列的日线行情（升序，最后一根为当前时点）
        as_of: 当前日期（datetime 或 date），用于判断最新周线是否「发展中」

    返回：
        (stage, label) —— stage 为 1-4，label 为 'Stage 2 上升 · 2A 上升初期' 这类展示标签；
        数据不足（周线 < 60 根 / 缺 close 列）时返回 (None, "—")
    """
    detail = compute_weinstein_detail(df, as_of=as_of)
    if detail is None:
        return None, "—"
    return detail["stage"], detail["label"]


def stage_label(stage: int | None, substage: str | None = None) -> str:
    """阶段编号 → 展示标签；None → 「—」。"""
    if stage is None:
        return "—"
    return _classical_stage_label(stage, substage)
