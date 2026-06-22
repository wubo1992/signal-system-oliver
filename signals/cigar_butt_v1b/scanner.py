"""
signals/cigar_butt_v1b/scanner.py — V1B 全市场扫描器

职责：扫描全市场股票，筛选出深度价值 + 盈利质量过关的标的
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from data.balance_sheet import get_full_financials, get_financials_ttm
from data.fetcher import fetch

from .filters import (
    CigarButtV1BCriteria,
    StockFundamentalsV1B,
    passes_filters_v1b,
    calculate_composite_score_v1b,
    calculate_ncav_v1b,
    calculate_p_ncav_v1b,
)


class CigarButtV1BSCanner:
    """
    V1B 扫描器：三层筛选（深度价值 + 盈利质量 + 流动性）

    使用方式：
        scanner = CigarButtV1BSCanner(config)
        candidates = scanner.scan(date)
    """

    def __init__(
        self,
        strategy_config: dict,
        market_data: dict[str, pd.DataFrame],
    ) -> None:
        self.cfg = strategy_config
        self.market_data = market_data

        # 解析配置
        # 第一层：深度价值（严格烟蒂版）
        self.max_p_ncav = self.cfg.get("max_p_ncav", 1.5)
        self.max_p_netnet = self.cfg.get("max_p_netnet", 2.0)
        self.max_p_b = self.cfg.get("max_p_b", 1.5)
        self.max_p_e = self.cfg.get("max_p_e", 10)
        self.max_debt_ratio = self.cfg.get("max_debt_ratio", 0.50)

        # 第二层：盈利质量
        self.require_positive_eps = self.cfg.get("require_positive_eps", True)
        self.require_positive_cfo = self.cfg.get("require_positive_cfo", True)
        self.max_revenue_decline_1y = self.cfg.get("max_revenue_decline_1y", 0.30)

        # 第三层：流动性
        self.min_market_cap = self.cfg.get("min_market_cap", 50_000_000)
        self.max_market_cap = self.cfg.get("max_market_cap", 10_000_000_000)
        self.min_avg_dollar_volume = self.cfg.get("min_avg_dollar_volume_20d", 200_000)

        # 仓位
        self.max_positions = self.cfg.get("max_positions", 25)

        # 评分权重
        self.score_weights = {
            'p_ncav': self.cfg.get("score_p_ncav_weight", 0.30),
            'p_e': self.cfg.get("score_pe_weight", 0.20),
            'debt': self.cfg.get("score_debt_weight", 0.20),
            'cfo': self.cfg.get("score_cfo_weight", 0.15),
            'size': self.cfg.get("score_size_weight", 0.15),
        }

        self.criteria = CigarButtV1BCriteria(
            max_p_ncav=self.max_p_ncav,
            max_p_netnet=self.max_p_netnet,
            max_p_b=self.max_p_b,
            max_p_e=self.max_p_e,
            max_debt_ratio=self.max_debt_ratio,
            require_positive_eps=self.require_positive_eps,
            require_positive_cfo=self.require_positive_cfo,
            max_revenue_decline_1y=self.max_revenue_decline_1y,
            min_market_cap=self.min_market_cap,
            max_market_cap=self.max_market_cap,
            min_avg_dollar_volume=self.min_avg_dollar_volume,
        )

    def scan(
        self,
        date: datetime,
        universe: Optional[list[str]] = None,
    ) -> list[tuple[str, float]]:
        """
        扫描全市场，返回符合条件的股票（按综合评分排序）

        参数：
            date: 当前日期
            universe: 股票列表，默认使用market_data中的所有股票

        返回：
            [(symbol, composite_score), ...] 按评分降序排列
        """
        if universe is None:
            universe = list(self.market_data.keys())

        print(f"[V1B扫描] 开始扫描 {len(universe)} 只股票...")

        candidates = []
        skipped = 0

        for symbol in universe:
            # 跳过指数
            if symbol.startswith("^"):
                continue

            # 获取市场数据
            df = self.market_data.get(symbol)
            if df is None or len(df) < 20:
                skipped += 1
                continue

            # 获取最新价格和成交量
            current_row = df.iloc[-1]
            current_price = float(current_row["close"])
            volume_20d = int(df["volume"].tail(20).mean())
            dollar_volume_20d = volume_20d * current_price

            # 获取财务数据
            financials = self._get_financials(symbol)
            if financials is None:
                skipped += 1
                continue

            bs = financials.get("balance_sheet", {})
            cf = financials.get("cash_flow", {})
            inc = financials.get("income", {})

            if bs.get('error') or cf.get('error') or inc.get('error'):
                skipped += 1
                continue

            # 计算市值
            market_cap = financials.get("market_cap", 0)
            if market_cap <= 0:
                market_cap = bs.get("market_cap", 0)

            if market_cap <= 0:
                skipped += 1
                continue

            # 构建股票数据
            stock = StockFundamentalsV1B(
                symbol=symbol,
                share_price=current_price,
                market_cap=market_cap,
                avg_volume_20d=volume_20d,
                avg_dollar_volume_20d=dollar_volume_20d,
                pe_ratio=inc.get("pe_ratio", financials.get("pe_ratio", 0)),
                pb_ratio=bs.get("pb_ratio", financials.get("pb_ratio", 0)),
                cash=bs.get("cash", 0),
                accounts_receivable=bs.get("accounts_receivable", 0),
                inventory=bs.get("inventory", 0),
                current_liabilities=bs.get("current_liabilities", 0),
                total_liabilities=bs.get("total_liabilities", 0),
                total_assets=bs.get("total_assets", 0),
                # 从 financials 顶层获取 TTM 数据（不是从空的 cf 字典）
                net_income_ttm=financials.get("net_income_ttm", 0) or cf.get("net_income_ttm", 0),
                operating_cash_flow_ttm=financials.get("operating_cash_flow_ttm", 0) or cf.get("operating_cash_flow_ttm", 0),
                net_income_history=inc.get("net_income_history", []),
                revenue_1y_ago=inc.get("revenue_1y_ago", 0),
                revenue_current=inc.get("revenue_current", inc.get("revenue", 0)),
                has_audit_issues=bs.get("has_audit_issues", False),
            )

            # 通过过滤器
            passed, reason = passes_filters_v1b(stock, self.criteria)
            if passed:
                candidates.append(stock)
                ncav = calculate_ncav_v1b(stock)
                p_ncav = calculate_p_ncav_v1b(stock, ncav)
                print(f"  [V1B] {symbol}: P/NCAV={p_ncav:.2f}, P/E={stock.pe_ratio:.1f}, CFO=${financials.get('operating_cash_flow_ttm', 0):,.0f}")
            else:
                skipped += 1

            # 防限流
            time.sleep(0.1)

        print(f"[V1B扫描] 完成: {len(candidates)} 只通过, {skipped} 只跳过")

        # 计算综合评分
        scored = []
        for stock in candidates:
            score = calculate_composite_score_v1b(stock, candidates, self.score_weights)
            scored.append((stock.symbol, score))

        # 按评分降序排列
        scored.sort(key=lambda x: x[1], reverse=True)

        # 取前N只
        selected = scored[: self.max_positions]
        print(f"[V1B扫描] 选取前 {len(selected)} 只")

        return selected

    def _get_financials(self, symbol: str) -> Optional[dict]:
        """获取股票完整财务数据"""
        try:
            bs_result = get_full_financials(symbol)
            if bs_result.get('error'):
                return None

            # 尝试获取TTM数据
            ttm_result = get_financials_ttm(symbol)
            if not ttm_result.get('error'):
                bs_result['net_income_ttm'] = ttm_result.get('net_income_ttm', 0)
                bs_result['operating_cash_flow_ttm'] = ttm_result.get('operating_cash_flow_ttm', 0)
                bs_result['revenue_ttm'] = ttm_result.get('revenue_ttm', 0)

            # 补充PE/PB（如果财务数据里有的话）
            bs = bs_result.get('balance_sheet', {})
            inc = bs_result.get('income', {})

            # 从market_cap和财务数据计算PE/PB
            market_cap = bs.get("market_cap", 0)
            if market_cap <= 0:
                market_cap = bs_result.get('market_cap', 0)

            # 使用 net_income_ttm（如果有的话）计算 PE
            net_income = bs_result.get('net_income_ttm', 0) or inc.get("net_income", 0)
            if market_cap > 0 and net_income > 0:
                bs_result["pe_ratio"] = market_cap / net_income
            else:
                bs_result["pe_ratio"] = 0

            if market_cap > 0 and bs.get("total_assets", 0) > 0:
                bs_result["pb_ratio"] = market_cap / bs.get("total_assets", 0)
            else:
                bs_result["pb_ratio"] = 0

            return bs_result

        except Exception as e:
            print(f"[V1B扫描] {symbol} 获取财务数据失败: {e}")
            return None

    def get_candidates_for_date(
        self,
        date: datetime,
        universe: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        获取候选股票列表（包含完整信息）
        """
        candidates = self.scan(date, universe)

        result = []
        for symbol, score in candidates:
            df = self.market_data.get(symbol)
            if df is not None:
                current_price = float(df.iloc[-1]["close"])
                result.append({
                    'symbol': symbol,
                    'score': score,
                    'current_price': current_price,
                })

        return result
