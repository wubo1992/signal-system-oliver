"""
signals/cigar_butt_v1b/filters.py — V1B 过滤器

深度价值 + 盈利质量过滤：在低P/NCAV基础上，要求盈利和现金流为正
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CigarButtV1BCriteria:
    """V1B 过滤器标准（现代化放宽版）"""

    # 第一层：深度价值（严格烟蒂版）
    max_p_ncav: float = 1.5       # 严格：P/NCAV < 1.5
    max_p_netnet: float = 2.0     # 严格：P/Net-Net < 2.0
    max_p_b: float = 1.5          # 严格：P/B < 1.5
    max_p_e: float = 10           # 严格：P/E < 10
    max_debt_ratio: float = 0.50  # 严格：负债率 < 50%

    # 第二层：盈利质量（保留核心要求）
    require_positive_eps: bool = True
    require_positive_cfo: bool = True
    min_profit_stability_years: int = 1   # 改为1年（原2年）
    max_revenue_decline_1y: float = 0.30  # 改为30%（原20%）

    # 第三层：流动性
    min_market_cap: float = 50_000_000   # 改为$5000万（原1亿）
    max_market_cap: float = 10_000_000_000  # $100亿
    min_avg_dollar_volume: float = 200_000   # $20万（原100万）


@dataclass
class StockFundamentalsV1B:
    """V1B 股票完整基本面数据"""
    symbol: str

    # 市场数据
    share_price: float
    market_cap: float
    avg_volume_20d: int
    avg_dollar_volume_20d: float

    # 估值
    pe_ratio: float
    pb_ratio: float

    # NCAV 相关
    cash: float
    accounts_receivable: float
    inventory: float
    current_liabilities: float
    total_liabilities: float
    total_assets: float

    # 盈利质量
    net_income_ttm: float  # 近4季度净利润
    operating_cash_flow_ttm: float  # 近4季度经营现金流
    net_income_history: list[float] = field(default_factory=list)  # 历史净利润
    revenue_1y_ago: float = 0
    revenue_current: float = 0

    # 排除标记
    has_audit_issues: bool = False


def calculate_ncav_v1b(stock: StockFundamentalsV1B) -> float:
    """计算NCAV"""
    return (
        stock.cash +
        0.75 * stock.accounts_receivable +
        0.5 * stock.inventory -
        stock.current_liabilities
    )


def calculate_p_ncav_v1b(stock: StockFundamentalsV1B, ncav: float) -> float:
    """计算P/NCAV"""
    if ncav <= 0:
        return float('inf')
    return stock.market_cap / ncav


def passes_filters_v1b(
    stock: StockFundamentalsV1B,
    criteria: CigarButtV1BCriteria,
) -> tuple[bool, Optional[str]]:
    """
    检查股票是否通过V1B所有过滤器（三层筛选）

    返回：
        (通过, 失败原因)
    """
    # ========== 第一层：深度价值 ==========

    ncav = calculate_ncav_v1b(stock)
    if ncav <= 0:
        return False, f"NCAV=${ncav:.0f} <= 0"

    p_ncav = calculate_p_ncav_v1b(stock, ncav)
    if p_ncav >= criteria.max_p_ncav:
        return False, f"P/NCAV={p_ncav:.2f} >= {criteria.max_p_ncav}"

    # Net-Net（更保守的清算价值）
    netnet = (
        stock.cash +
        0.67 * stock.accounts_receivable +
        0.5 * stock.inventory -
        stock.total_liabilities
    )
    if netnet > 0:
        p_netnet = stock.market_cap / netnet
        if p_netnet >= criteria.max_p_netnet:
            return False, f"P/Net-Net={p_netnet:.2f} >= {criteria.max_p_netnet}"

    # P/B
    if stock.pb_ratio <= 0 or stock.pb_ratio >= criteria.max_p_b:
        return False, f"P/B={stock.pb_ratio:.2f} 不在 (0, {criteria.max_p_b})"

    # P/E
    if stock.pe_ratio <= 0 or stock.pe_ratio >= criteria.max_p_e:
        return False, f"P/E={stock.pe_ratio:.1f} 不在 (0, {criteria.max_p_e})"

    # 负债率
    if stock.total_assets > 0:
        debt_ratio = stock.total_liabilities / stock.total_assets
        if debt_ratio >= criteria.max_debt_ratio:
            return False, f"负债率={debt_ratio:.1%} >= {criteria.max_debt_ratio:.1%}"

    # ========== 第二层：盈利质量 ==========

    # 净利润TTM
    if criteria.require_positive_eps and stock.net_income_ttm <= 0:
        return False, f"净利润TTM=${stock.net_income_ttm:.0f} <= 0"

    # 经营现金流TTM
    if criteria.require_positive_cfo and stock.operating_cash_flow_ttm <= 0:
        return False, f"经营现金流TTM=${stock.operating_cash_flow_ttm:.0f} <= 0"

    # 盈利稳定性：近2年至少1年盈利
    if criteria.min_profit_stability_years > 0 and stock.net_income_history:
        profitable_years = sum(1 for ni in stock.net_income_history if ni > 0)
        if profitable_years == 0:
            return False, "近2年无盈利年份"

    # 营收下降
    if criteria.max_revenue_decline_1y > 0 and stock.revenue_1y_ago > 0:
        revenue_decline = (stock.revenue_1y_ago - stock.revenue_current) / stock.revenue_1y_ago
        if revenue_decline >= criteria.max_revenue_decline_1y:
            return False, f"营收下降={revenue_decline:.1%} >= {criteria.max_revenue_decline_1y:.1%}"

    # ========== 第三层：流动性 ==========

    if not (criteria.min_market_cap <= stock.market_cap <= criteria.max_market_cap):
        mcap_m = stock.market_cap / 1_000_000
        min_m = criteria.min_market_cap / 1_000_000
        max_m = criteria.max_market_cap / 1_000_000
        return False, f"市值${mcap_m:.0f}M不在${min_m:.0f}M-${max_m:.0f}M"

    if stock.avg_dollar_volume_20d < criteria.min_avg_dollar_volume:
        return False, f"日均成交额${stock.avg_dollar_volume_20d/1e6:.1f}M < ${criteria.min_avg_dollar_volume/1e6:.1f}M"

    # ========== 排除清单 ==========

    if stock.has_audit_issues:
        return False, "审计问题"

    return True, None


def calculate_composite_score_v1b(
    stock: StockFundamentalsV1B,
    all_stocks: list[StockFundamentalsV1B],
    weights: dict,
) -> float:
    """
    计算V1B综合评分（0-100，越高越好）

    各因子评分逻辑：
    - P/NCAV：越低越好，取百分位排名
    - P/E：越低越好，取百分位排名
    - 负债率：越低越好，取百分位排名
    - CFO/股价：越高越好，取百分位排名
    - 市值：中等偏好，取与中位数的接近度
    """
    scores = {}

    # P/NCAV 评分（越低越好）
    p_ncav = calculate_p_ncav_v1b(stock, calculate_ncav_v1b(stock))
    if p_ncav < float('inf'):
        p_ncav_values = [calculate_p_ncav_v1b(s, calculate_ncav_v1b(s)) for s in all_stocks if calculate_ncav_v1b(s) > 0]
        if p_ncav_values:
            rank = sum(1 for v in p_ncav_values if v >= p_ncav) / len(p_ncav_values)
            scores['p_ncav'] = rank * 100 * weights.get('p_ncav', 0.30)
    if 'p_ncav' not in scores:
        scores['p_ncav'] = 0

    # P/E 评分（越低越好）
    if stock.pe_ratio > 0:
        pe_values = [s.pe_ratio for s in all_stocks if s.pe_ratio > 0]
        if pe_values:
            rank = sum(1 for v in pe_values if v >= stock.pe_ratio) / len(pe_values)
            scores['p_e'] = rank * 100 * weights.get('p_e', 0.20)
    if 'p_e' not in scores:
        scores['p_e'] = 0

    # 负债率评分（越低越好）
    debt_values = [s.total_liabilities / s.total_assets for s in all_stocks if s.total_assets > 0]
    if debt_values and stock.total_assets > 0:
        debt_ratio = stock.total_liabilities / stock.total_assets
        rank = sum(1 for v in debt_values if v >= debt_ratio) / len(debt_values)
        scores['debt'] = rank * 100 * weights.get('debt', 0.20)
    if 'debt' not in scores:
        scores['debt'] = 0

    # CFO/股价评分（越高越好）
    cfo_per_price = stock.operating_cash_flow_ttm / stock.market_cap if stock.market_cap > 0 else 0
    if cfo_per_price > 0:
        cfo_values = [s.operating_cash_flow_ttm / s.market_cap for s in all_stocks if s.market_cap > 0 and s.operating_cash_flow_ttm > 0]
        if cfo_values:
            rank = sum(1 for v in cfo_values if v <= cfo_per_price) / len(cfo_values)
            scores['cfo'] = rank * 100 * weights.get('cfo', 0.15)
    if 'cfo' not in scores:
        scores['cfo'] = 0

    # 市值评分（中等偏好）
    if all_stocks and stock.market_cap > 0:
        cap_values = [s.market_cap for s in all_stocks if s.market_cap > 0]
        if cap_values:
            import numpy as np
            median_cap = np.median(cap_values)
            cap_ratio = min(stock.market_cap, median_cap * 2) / max(stock.market_cap, median_cap * 0.5)
            cap_score = min(cap_ratio, 1.0) * 100 * weights.get('size', 0.15)
            scores['size'] = cap_score
    if 'size' not in scores:
        scores['size'] = 0

    total_score = sum(scores.values())
    return total_score
