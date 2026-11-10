"""
strategies/v_oliver_kell/weinstein_stage.py — Weinstein 四阶段分析（Stage Analysis）

Stan Weinstein《Secrets for Profiting in Bull and Bear Markets》的核心框架：
把个股生命周期切成四个阶段，用「均线结构 + 价格相对均线位置」判断当前处于哪一段。

    Stage 1 筑底（Basing）    — 长期均线走平/微升，价格在 MA200 上方缩量横盘，筹码换手
    Stage 2 上升（Markup）    — 均线多头排列，价格沿 MA30 上行，趋势健康
    Stage 3 做顶（Topping）   — 上升趋势衰竭：涨势放缓、跌破 MA30、量能萎缩
    Stage 4 下跌（Decline）   — 跌破 MA150/MA200 且长期均线转头向下，熊市阶段

## 本实现的判定规则（确定性、可复算）

均线：MA30 / MA150 / MA200（简单移动平均）。
斜率：MA30 vs 5 根前、MA150 vs 10 根前、MA200 vs 20 根前，百分比变化（%）。

两个中间量：

    long_up   = 价 > MA150 且 MA150 斜率 > 0      （长期上升趋势成立）
    short_bad = 价 < MA30 且 MA30 斜率 < -1%      （中期动能确认走坏）
    ext       = 近 10 根相对 MA30 的最大正乖离（%）（判断是不是「涨过头后回落」）

按顺序判定，命中即返回：

  1. Stage 4（下跌）
     - 价 < MA150 且 MA150 斜率 ≤ 0        （长期均线走坏并被跌破）
     - 或 价 < MA200 且 MA200 斜率 < 0
  2. Stage 3（做顶）
     - long_up 且 short_bad
     - 且（近 10 根曾相对 MA30 有 ≥ 5% 正乖离，或 MA150 斜率 ≥ 1%）
       —— 即：涨势明确、长期趋势未坏，但中期动能已断
  3. Stage 2（上升）
     - long_up 且 NOT short_bad（回踩 MA30 途中仍算上升，未确认破位）
  4. Stage 1（筑底）
     - 价 > MA200 且（MA150 未上行 或 价 < MA150）—— 长期均线之上但动能未确认
     - 或 long_up 且 short_bad（长期未坏、动能已失、回撤到 MA150 附近 → 整理）
  5. 兜底
     - 价 < MA200 → Stage 4；否则 Stage 3

要点：Stage 2 允许「回踩 MA30」——Weinstein 认为上升趋势中的回调仍属于 Stage 2，
只有中期动能确认走坏（short_bad）才降级为 Stage 3（做顶）或 Stage 1（整理）。

## 与 Oliver Kell 六阶段的关系

两者不冲突，观察角度不同：
    - Kell 六阶段看**短期价格行为**（楔形、突破、回踩），决定「今天动不动手」
    - Weinstein 四阶段看**中长期趋势位置**，决定「这只票现在该不该碰」

典型组合：Stage 2 + Wedge Pop = 最强买点；Stage 4 + 任何买入信号 = 逆势，需降权；
Stage 1 + Base Tightening = 筑底观察期，突破后有望进 Stage 2。

## 数据要求

MA200 需要至少 200 根 K 线（不足返回 None，输出显示为「—」）。
新股 / 上市不足一年的股票无法判定阶段，这是方法的固有限制，不做插值猜测。
"""

import pandas as pd

# 阶段编号 → 展示标签
STAGE_LABELS = {
    1: "Stage 1 筑底",
    2: "Stage 2 上升",
    3: "Stage 3 做顶",
    4: "Stage 4 下跌",
}

# 均线窗口
_MA30, _MA150, _MA200 = 30, 150, 200
# 斜率回看根数
_SLOPE_30, _SLOPE_150, _SLOPE_200 = 5, 10, 20
# 判定 Stage 3 时「涨过头」的阈值：近 10 根相对 MA30 的最大正乖离（%）
_EXT_MIN = 5.0
# MA30 斜率跌破该值（%）才算动能衰竭
_S30_WEAK = -1.0
# MA150 斜率达到该值（%）时，长期趋势足够明确，可判 Stage 3（做顶）
_S150_STRONG = 1.0
# 至少需要的 K 线根数
_MIN_BARS = _MA200


def _slope(series: pd.Series, lookback: int) -> float:
    """末端相对 lookback 根之前的百分比变化（%）。数据不足时缩短窗口，样本太少返回 0.0。"""
    s = series.dropna()
    if len(s) < 2:
        return 0.0
    lb = min(lookback, len(s) - 1)
    last = float(s.iloc[-1])
    base = float(s.iloc[-1 - lb])
    if base <= 0:
        return 0.0
    return (last / base - 1.0) * 100.0


def _classify(
    price: float,
    ma30: float,
    ma150: float,
    ma200: float,
    s30: float,
    s150: float,
    s200: float,
    extension: float,
) -> int:
    """按判定规则给出阶段编号（1-4）。规则见模块 docstring。"""
    long_up = price > ma150 and s150 > 0
    short_bad = price < ma30 and s30 < _S30_WEAK

    # ── Stage 4：长期趋势被破坏 ──
    if price < ma150 and s150 <= 0:
        return 4
    if price < ma200 and s200 < 0:
        return 4

    # ── Stage 3：涨势明确、长期趋势未坏，但中期动能已断 ──
    if long_up and short_bad and (extension >= _EXT_MIN or s150 >= _S150_STRONG):
        return 3

    # ── Stage 2：长期上升趋势成立，回踩不算破位 ──
    if long_up and not short_bad:
        return 2

    # ── Stage 1：长期均线之上但动能未确认 / 回撤整理 ──
    if price > ma200 and (s150 <= 0 or price < ma150):
        return 1
    if long_up and short_bad:
        return 1

    # ── 兜底 ──
    return 4 if price < ma200 else 3


def compute_weinstein_stage(df: pd.DataFrame | None) -> tuple[int | None, str]:
    """
    计算单只股票的 Weinstein 阶段。

    参数：
        df: 含 close 列的行情 DataFrame（升序，最后一根为当前时点）

    返回：
        (stage, label) —— stage 为 1-4，label 为展示标签；
        数据不足（K 线 < 200 根 / 缺 close 列）时返回 (None, "—")
    """
    if df is None or df.empty or "close" not in df.columns:
        return None, "—"

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < _MIN_BARS:
        return None, "—"

    ma30 = close.rolling(_MA30).mean()
    ma150 = close.rolling(_MA150).mean()
    ma200 = close.rolling(_MA200).mean()

    if pd.isna(ma200.iloc[-1]):
        return None, "—"

    price = float(close.iloc[-1])
    m30 = float(ma30.iloc[-1])
    m150 = float(ma150.iloc[-1])
    m200 = float(ma200.iloc[-1])

    s30 = _slope(ma30, _SLOPE_30)
    s150 = _slope(ma150, _SLOPE_150)
    s200 = _slope(ma200, _SLOPE_200)

    # 近 10 根相对 MA30 的最大正乖离（%）：判断是否「涨过头后回落」
    tail_close = close.iloc[-10:]
    tail_ma30 = ma30.iloc[-10:]
    if len(tail_close) == len(tail_ma30) and not tail_ma30.isna().all():
        extension = float(((tail_close / tail_ma30) - 1.0).max() * 100.0)
    else:
        extension = 0.0

    stage = _classify(price, m30, m150, m200, s30, s150, s200, extension)
    return stage, STAGE_LABELS[stage]


def stage_label(stage: int | None) -> str:
    """阶段编号 → 展示标签；None → 「—」。"""
    if stage is None:
        return "—"
    return STAGE_LABELS.get(stage, "—")
