"""
data/balance_sheet.py — 资产负债表数据获取模块

职责：获取股票资产负债表数据（现金、应收账款、存货、流动负债等），
      用于计算格雷厄姆 NCAV（Net Current Asset Value）。

数据来源优先级：
  1. SEC EDGAR 本地缓存（完整 XBRL 字段，覆盖 3600+ 股票）
  2. Polygon.io API（作为 fallback）

NCAV 公式：NCAV = 现金 + 0.75×应收账款 + 0.5×存货 - 全部流动负债
"""

import json
import os
import pickle
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
POLYGON_BASE_URL = "https://api.polygon.io"

CACHE_DIR = Path(__file__).parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)

# SEC EDGAR 缓存目录
SEC_CACHE_DIR = Path(__file__).parent / "cache"


def _sec_cache_path(symbol: str) -> Path:
    return SEC_CACHE_DIR / f"sec_edgar_{symbol}.json"


def _get_tag_sec(facts: dict, namespace: str, tag: str) -> Optional[float]:
    """从 SEC EDGAR facts 中提取最新一期的值"""
    if namespace in facts and tag in facts[namespace]:
        units = facts[namespace][tag].get("units", {})
        if "USD" in units and units["USD"]:
            return units["USD"][-1]["val"]
        elif "USD/shares" in units and units["USD/shares"]:
            return units["USD/shares"][-1]["val"]
    return None


def _get_ttm_from_sec(facts: dict, namespace: str, tag: str) -> tuple[float, int]:
    """
    从 SEC EDGAR facts 中计算 TTM（最近4个季度之和）

    返回：
        (ttm_value, quarter_count)
    """
    if namespace not in facts or tag not in facts[namespace]:
        return 0.0, 0

    units = facts[namespace][tag].get("units", {})
    records = units.get("USD", [])
    if not records:
        return 0.0, 0

    # 按 end date 降序排序
    sorted_records = sorted(records, key=lambda x: x.get("end", ""), reverse=True)

    # 提取4个唯一季度（避免同一季度多个报告的重复计算）
    ttm = 0.0
    count = 0
    seen_frames: set[str] = set()

    for r in sorted_records:
        frame = r.get("frame", "")
        val = r.get("val", 0)

        # 只取有 frame 标记的季度数据，且只取每个季度一次
        if frame and "Q" in frame:
            if frame not in seen_frames:
                ttm += val
                seen_frames.add(frame)
                count += 1
                if count >= 4:
                    break

    return ttm, count


def _load_sec_edgar(symbol: str) -> Optional[dict]:
    """从 SEC EDGAR 本地缓存加载财务数据"""
    cache_path = _sec_cache_path(symbol)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r") as f:
            data = json.load(f)

        facts = data.get("facts", {})
        us_gaap = facts.get("us-gaap", {})

        # 提取 NCAV 相关字段
        cash = _get_tag_sec(facts, "us-gaap", "CashAndCashEquivalentsAtCarryingValue")
        if cash is None:
            cash = _get_tag_sec(facts, "us-gaap", "Cash")

        ar = _get_tag_sec(facts, "us-gaap", "AccountsReceivable")
        if ar is None:
            ar = _get_tag_sec(facts, "us-gaap", "AccountsReceivableNetCurrent")

        inventory = _get_tag_sec(facts, "us-gaap", "Inventory")
        if inventory is None:
            inventory = _get_tag_sec(facts, "us-gaap", "InventoryNet")

        current_liabilities = _get_tag_sec(facts, "us-gaap", "LiabilitiesCurrent")
        total_liabilities = _get_tag_sec(facts, "us-gaap", "Liabilities")
        total_assets = _get_tag_sec(facts, "us-gaap", "Assets")

        # NCAV 公式
        if cash is not None and current_liabilities is not None and cash > 0 and current_liabilities > 0:
            ncav = cash + 0.75 * (ar or 0) + 0.5 * (inventory or 0) - current_liabilities
        else:
            ncav = None

        # TTM 数据
        net_income = _get_tag_sec(facts, "us-gaap", "NetIncomeLoss")
        operating_cfo = _get_tag_sec(facts, "us-gaap", "NetCashProvidedByUsedInOperatingActivities")
        if operating_cfo is None:
            operating_cfo = _get_tag_sec(facts, "us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
        revenue = _get_tag_sec(facts, "us-gaap", "Revenues")

        return {
            'cash': cash,
            'accounts_receivable': ar,
            'inventory': inventory,
            'current_liabilities': current_liabilities,
            'total_liabilities': total_liabilities,
            'total_assets': total_assets,
            'ncav': ncav,
            'net_income': net_income,
            'operating_cfo': operating_cfo,
            'revenue': revenue,
            'source': 'sec_edgar',
            'error': None,
        }
    except Exception:
        return None


def _cache_path(symbol: str, data_type: str) -> Path:
    return CACHE_DIR / f"polygon_{data_type}_{symbol}.pkl"


def _is_cache_valid(path: Path, max_age_days: int = 7) -> bool:
    if not path.exists():
        return False
    file_age = datetime.now().timestamp() - path.stat().st_mtime
    return file_age < (max_age_days * 86400)


def get_balance_sheet(symbol: str) -> dict:
    """
    获取资产负债表数据

    返回：
        {
            'cash': float,                  # 现金及等价物
            'accounts_receivable': float,   # 应收账款
            'inventory': float,             # 存货
            'current_liabilities': float,   # 流动负债
            'total_liabilities': float,     # 总负债
            'total_assets': float,          # 总资产
            'ncav': float,                  # NCAV
            'fiscal_year': str,
            'error': str/None
        }
    """
    # 优先从 SEC EDGAR 缓存读取
    sec_data = _load_sec_edgar(symbol)
    if sec_data and sec_data.get('ncav') is not None:
        print(f"[BalanceSheet] {symbol} 从SEC EDGAR加载")
        return {
            'cash': sec_data.get('cash', 0) or 0,
            'accounts_receivable': sec_data.get('accounts_receivable', 0) or 0,
            'inventory': sec_data.get('inventory', 0) or 0,
            'current_liabilities': sec_data.get('current_liabilities', 0) or 0,
            'total_liabilities': sec_data.get('total_liabilities', 0) or 0,
            'total_assets': sec_data.get('total_assets', 0) or 0,
            'ncav': sec_data.get('ncav', 0),
            'source': 'sec_edgar',
            'error': None,
        }

    # Fallback: 从 Polygon 缓存读取
    cache_path = _cache_path(symbol, "balance_sheet")
    if _is_cache_valid(cache_path):
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            print(f"[BalanceSheet] {symbol} 从Polygon缓存加载")
            return cached
        except Exception:
            pass

    # Fallback: 调用 Polygon API
    if not POLYGON_API_KEY:
        return {'error': 'No API Key (Polygon) and no SEC EDGAR cache'}

    url = f"{POLYGON_BASE_URL}/v2/reference/financials/{symbol}"
    params = {
        "apiKey": POLYGON_API_KEY,
        "period": "quarterly",
        "pageSize": 1,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            return {'error': f'HTTP {resp.status_code}'}

        data = resp.json()
        if data.get("status") != "OK":
            return {'error': f'API Error: {data.get("status")}'}

        results = data.get("results", [])
        if not results:
            return {'error': 'No financial data available'}

        latest = results[0]

        cash = latest.get('cashAndEquivalents', 0) or 0
        accounts_receivable = latest.get('receivables', 0) or 0
        inventory = latest.get('inventory', 0) or 0
        current_liabilities = latest.get('liabilitiesCurrent', 0) or 0
        total_liabilities = latest.get('liabilities', 0) or 0
        total_assets = latest.get('assets', 0) or 0

        ncav = cash + (0.75 * accounts_receivable) + (0.5 * inventory) - current_liabilities

        result = {
            'cash': float(cash),
            'accounts_receivable': float(accounts_receivable),
            'inventory': float(inventory),
            'current_liabilities': float(current_liabilities),
            'total_liabilities': float(total_liabilities),
            'total_assets': float(total_assets),
            'ncav': float(ncav),
            'source': 'polygon',
            'error': None,
        }

        try:
            with open(cache_path, "wb") as f:
                pickle.dump(result, f)
        except Exception:
            pass

        return result

    except Exception as e:
        return {'error': str(e)}


def get_market_cap(symbol: str) -> float:
    """获取市值（优先用 nasdaq_market_caps.json 缓存）"""
    # 先从 nasdaq 市值缓存读取
    mcap_cache = SEC_CACHE_DIR / "nasdaq_market_caps.json"
    if mcap_cache.exists():
        try:
            with open(mcap_cache, "r") as f:
                cached_mcaps = json.load(f)
            if symbol in cached_mcaps and cached_mcaps[symbol] > 0:
                return cached_mcaps[symbol]
        except Exception:
            pass

    # Fallback: Polygon 缓存
    cache_path = _cache_path(symbol, "market_cap")
    if _is_cache_valid(cache_path, max_age_days=1):
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            return cached.get('market_cap', 0)
        except Exception:
            pass

    if not POLYGON_API_KEY:
        return 0

    url = f"{POLYGON_BASE_URL}/v2/aggs/ticker/{symbol}/prev"
    params = {"apiKey": POLYGON_API_KEY}

    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                close_price = results[0].get('c', 0)
                shares = _get_shares_outstanding(symbol)
                if shares > 0 and close_price > 0:
                    mcap = close_price * shares
                    with open(cache_path, "wb") as f:
                        pickle.dump({'market_cap': mcap, 'price': close_price, 'shares': shares}, f)
                    return mcap
    except Exception:
        pass

    return 0


def _get_shares_outstanding(symbol: str) -> float:
    """获取流通股数"""
    cache_path = _cache_path(symbol, "shares")

    if _is_cache_valid(cache_path, max_age_days=7):
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            return cached.get('shares', 0)
        except Exception:
            pass

    if not POLYGON_API_KEY:
        return 0

    url = f"{POLYGON_BASE_URL}/v2/reference/financials/{symbol}"
    params = {"apiKey": POLYGON_API_KEY, "period": "quarterly", "pageSize": 1}

    try:
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", [])
            if results:
                shares = results[0].get('weightedAverageByBasicShs', 0) or 0
                if shares:
                    with open(cache_path, "wb") as f:
                        pickle.dump({'shares': shares}, f)
                    return shares
    except Exception:
        pass

    return 0


def calculate_ncav(balance_sheet: dict) -> float:
    """计算 NCAV"""
    if balance_sheet.get('error'):
        return 0
    return balance_sheet.get('ncav', 0)


def get_full_financials(symbol: str) -> dict:
    """
    获取完整财务数据

    返回：
        {
            'balance_sheet': dict,
            'ncav': float,
            'market_cap': float,
            'p_ncav': float,
            'error': str/None
        }
    """
    bs = get_balance_sheet(symbol)
    if bs.get('error'):
        return {'error': bs['error']}

    market_cap = get_market_cap(symbol)
    ncav = bs.get('ncav', 0)
    p_ncav = market_cap / ncav if ncav > 0 else float('inf')

    return {
        'balance_sheet': bs,
        'ncav': ncav,
        'market_cap': market_cap,
        'p_ncav': p_ncav,
        'error': None,
    }


def get_financials_ttm(symbol: str) -> dict:
    """
    获取 TTM（Trailing Twelve Months）财务数据

    优先从 SEC EDGAR 缓存读取并计算 TTM（4季度求和），
    Fallback 到 Polygon API（需要 API Key）。

    如果无法获取 TTM，返回最新可用数据（年度或单季度）并标记 source。

    返回：
        {
            'net_income_ttm': float,
            'operating_cash_flow_ttm': float,
            'revenue_ttm': float,
            'source': str,
            'data_type': str,  # 'ttm' | 'annual' | 'quarterly'
            'error': str/None
        }
    """
    cache_path = _cache_path(symbol, "financials_ttm")

    # 只有有效且来源可靠的缓存才使用
    if _is_cache_valid(cache_path, max_age_days=7):
        try:
            with open(cache_path, "rb") as f:
                cached = pickle.load(f)
            # 只用 SEC EDGAR TTM 缓存，Polygon 缓存可能有问题
            if cached.get('source') == 'sec_edgar_ttm' and cached.get('error') is None:
                print(f"[FinancialsTTM] {symbol} 从缓存加载")
                return cached
        except Exception:
            pass

    # 优先从 SEC EDGAR 缓存读取并计算 TTM
    cache_path_sec = _sec_cache_path(symbol)
    if cache_path_sec.exists():
        try:
            with open(cache_path_sec, "r") as f:
                data = json.load(f)

            facts = data.get("facts", {})
            us_gaap = facts.get("us-gaap", {})

            # 计算 TTM（4季度求和）
            ni_ttm, ni_count = _get_ttm_from_sec(facts, "us-gaap", "NetIncomeLoss")
            cfo_ttm, cfo_count = _get_ttm_from_sec(facts, "us-gaap", "NetCashProvidedByUsedInOperatingActivities")
            rev_ttm, rev_count = _get_ttm_from_sec(facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax")

            if ni_count >= 4:  # 有4个季度数据，用 TTM
                result = {
                    'net_income_ttm': float(ni_ttm),
                    'operating_cash_flow_ttm': float(cfo_ttm),
                    'revenue_ttm': float(rev_ttm),
                    'source': 'sec_edgar_ttm',
                    'data_type': 'ttm',
                    'quarters_used': ni_count,
                    'error': None,
                }
                _cache_ttm_result(cache_path, result, symbol, 'TTM')
                return result
            elif ni_count >= 1:  # 只有1-3个季度，用最新季度数据
                # 取最新一期
                ni_annual = _get_tag_sec(facts, "us-gaap", "NetIncomeLoss") or 0
                cfo_annual = _get_tag_sec(facts, "us-gaap", "NetCashProvidedByUsedInOperatingActivities") or 0
                rev_annual = _get_tag_sec(facts, "us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax") or 0
                result = {
                    'net_income_ttm': float(ni_annual),
                    'operating_cash_flow_ttm': float(cfo_annual),
                    'revenue_ttm': float(rev_annual),
                    'source': 'sec_edgar_quarterly',
                    'data_type': 'quarterly',
                    'quarters_used': ni_count,
                    'error': None,
                }
                _cache_ttm_result(cache_path, result, symbol, f'季度({ni_count}Q)')
                return result
        except Exception as e:
            print(f"[FinancialsTTM] {symbol} SEC EDGAR读取失败: {e}")

    # Fallback: Polygon API（需要有效的 API Key）
    if not POLYGON_API_KEY:
        return {'error': f'No Polygon API Key and no valid SEC EDGAR data for {symbol}'}

    url = f"{POLYGON_BASE_URL}/v2/reference/financials/{symbol}"
    params = {
        "apiKey": POLYGON_API_KEY,
        "period": "quarterly",
        "pageSize": 4,
    }

    try:
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code != 200:
            return {'error': f'HTTP {resp.status_code}'}

        data = resp.json()
        if data.get("status") != "OK":
            return {'error': f'API Error: {data.get("status")}'}

        results = data.get("results", [])
        if not results:
            return {'error': 'No financial data available'}

        net_income_ttm = 0.0
        operating_cash_flow_ttm = 0.0
        revenue_ttm = 0.0

        for q in results[:4]:
            # Polygon 字段名与 SEC EDGAR 不同
            ni = q.get('netIncome', 0) or q.get('netIncomeLoss', 0) or 0
            cfo = q.get('netCashFlowFromOperations', 0) or q.get('netCashProvidedByUsedInOperatingActivities', 0) or 0
            rev = q.get('revenue', 0) or q.get('revenues', 0) or 0
            net_income_ttm += ni
            operating_cash_flow_ttm += cfo
            revenue_ttm += rev

        result = {
            'net_income_ttm': float(net_income_ttm),
            'operating_cash_flow_ttm': float(operating_cash_flow_ttm),
            'revenue_ttm': float(revenue_ttm),
            'source': 'polygon',
            'data_type': 'ttm',
            'error': None,
        }
        _cache_ttm_result(cache_path, result, symbol, 'Polygon')
        return result

    except Exception as e:
        return {'error': str(e)}


def _cache_ttm_result(cache_path: Path, result: dict, symbol: str, label: str) -> None:
    """缓存TTM结果"""
    try:
        with open(cache_path, "wb") as f:
            pickle.dump(result, f)
        print(f"[FinancialsTTM] {symbol} 从{label}缓存")
    except Exception as e:
        print(f"[FinancialsTTM] {symbol} 缓存失败: {e}")


if __name__ == "__main__":
    # 测试
    for symbol in ['AMWL', 'AEHR']:
        print(f"\n--- {symbol} ---")
        result = get_balance_sheet(symbol)
        if result.get('error'):
            print(f"Error: {result['error']}")
        else:
            print(f"Cash: ${result.get('cash', 0):,.0f}")
            print(f"Accounts Receivable: ${result.get('accounts_receivable', 0):,.0f}")
            print(f"Inventory: ${result.get('inventory', 0):,.0f}")
            print(f"Current Liabilities: ${result.get('current_liabilities', 0):,.0f}")
            print(f"NCAV: ${result.get('ncav', 0):,.0f}")
            print(f"Source: {result.get('source', 'unknown')}")

            mcap = get_market_cap(symbol)
            p_ncav = mcap / result.get('ncav', 1) if result.get('ncav', 0) > 0 else float('inf')
            print(f"Market Cap: ${mcap/1e9:.2f}B")
            print(f"P/NCAV: {p_ncav:.2f}")

        ttm = get_financials_ttm(symbol)
        if ttm.get('error'):
            print(f"TTM Error: {ttm['error']}")
        else:
            print(f"Net Income TTM: ${ttm.get('net_income_ttm', 0):,.0f}")
            print(f"CFO TTM: ${ttm.get('operating_cash_flow_ttm', 0):,.0f}")
            print(f"Revenue TTM: ${ttm.get('revenue_ttm', 0):,.0f}")

        time.sleep(0.5)
