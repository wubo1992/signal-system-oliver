"""
universe/manager.py — 股票池管理器

职责：
1. 从 UNIVERSE.md 读取手动维护的股票（来源 A）——唯一权威来源
2. 从 Alpaca 新闻 API 自动获取被媒体关注的股票（来源 B）
3. 从 Wikipedia 获取指定指数成分股（来源 C，可配置：sp500 / nasdaq100）
4. 三个来源取并集，返回最终股票池

UNIVERSE.md 解析规则：
- 读取所有 Markdown 表格行（格式：| TICKER | 公司 | 简介 |）
- 遇到「## 待移出记录」节标题时停止（此节之后的股票不计入）
- 自动跳过表头行（含中文）、分隔行（含 ---）

缓存文件：data/universe_cache.json
格式：{"NVDA": {"last_mentioned": "2026-03-03"}, ...}

更新策略：
- 首次运行（无缓存）：抓取过去 365 天的新闻
- 后续运行：只抓取昨天的新闻（增量更新）
- 超过 max_age_days 天未被提及的股票，自动移出缓存
"""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .alpaca_fetcher import fetch_news_symbols
from .index_fetcher import get_index_symbols

# 缓存文件路径：signal_system/data/universe_cache.json
CACHE_FILE = Path(__file__).parent.parent / "data" / "universe_cache.json"

# UNIVERSE.md 路径：signal_system/UNIVERSE.md
UNIVERSE_MD = Path(__file__).parent.parent / "UNIVERSE.md"

# 股票代码正则：1-6 位大写字母或数字，可带一个点后缀（如 BRK.B / 0700.HK / 2330.TW）
_TICKER_RE = re.compile(r'^[A-Z0-9]{1,6}(\.[A-Z0-9]{1,5})?$')


def _read_universe_md(filename: str | None = None) -> list[str]:
    """
    从 UNIVERSE.md 解析正式手动股票池。

    参数：
        filename：可选，指定Universe文件名。默认为 "UNIVERSE.md"。
                   用于测试时传入 "UNIVERSE_test.md" 等副本。
    """
    universe_file = Path(__file__).parent.parent / (filename or "UNIVERSE.md")
    if not universe_file.exists():
        print(f"[警告] {filename or 'UNIVERSE.md'} 不存在，手动股票池为空：{universe_file}")
        return []

    symbols: list[str] = []
    in_code_block = False

    with open(universe_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            # 跟踪代码块（``` 围栏内的内容不解析）
            if line.startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue

            # 遇到「## 待移出记录」节标题时停止（此节之后不再有正式股票）
            if line.startswith("##") and "待移出记录" in line:
                break

            # 只处理表格行
            if not line.startswith("|"):
                continue

            parts = [p.strip() for p in line.split("|")]
            # split("|") 的结果：["", "TICKER", "公司", "简介", ""]
            if len(parts) < 3:
                continue

            ticker = parts[1]

            # 跳过表头、分隔行、空格
            if not ticker or not _TICKER_RE.match(ticker):
                continue

            symbols.append(ticker)

    result = sorted(set(symbols))
    return result


def get_universe(config: dict) -> list[str]:
    """
    返回最终股票池（UNIVERSE.md ∪ 指数成分股 ∪ Alpaca 自动池，去重排序）。

    参数：
        config: 读取自 config.yaml 的完整配置字典

    返回：
        股票代码列表，如 ["AAPL", "GOOGL", "META", "MSFT", "NVDA"]
    """
    auto_cfg = config.get("auto_universe", {})
    include_indices = auto_cfg.get("include_indices", [])

    # 来源 A：UNIVERSE.md 手动维护的股票
    manual = _read_universe_md()

    # 来源 B：指数成分股（S&P 500 / Nasdaq 100，由 config 控制）
    index_symbols = get_index_symbols(include_indices) if include_indices else []

    # 合并：只用手动的 + 指数，不包含自动池
    combined = sorted(set(manual) | set(index_symbols))
    print(
        f"[股票池] 最终股票池：{len(combined)} 只 "
        f"（手动 {len(manual)} + 指数 {len(index_symbols)}）"
    )
    return combined


def _get_auto_symbols(initial_lookback_days: int, max_age_days: int) -> list[str]:
    """
    获取自动股票池（Alpaca 新闻 API 来源），管理缓存。

    缓存逻辑：
    - 无缓存：全量抓取过去 initial_lookback_days 天
    - 有缓存：只抓取昨天（增量更新），然后清除过期股票
    """
    cache = _load_cache()
    today = datetime.now(tz=timezone.utc).date()

    if not cache:
        # 首次运行：全量抓取
        print(f"[股票池] 首次运行，抓取过去 {initial_lookback_days} 天的新闻...")
        new_symbols = fetch_news_symbols(lookback_days=initial_lookback_days)
    else:
        # 后续运行：只抓昨天（增量更新）
        print("[股票池] 增量更新：抓取昨天的新闻...")
        new_symbols = fetch_news_symbols(lookback_days=1)

    # 合并新数据到缓存
    for symbol, last_mentioned in new_symbols.items():
        cache[symbol] = {"last_mentioned": last_mentioned}

    # 清除超过 max_age_days 的过期股票
    cutoff_date = (today - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    before_count = len(cache)
    cache = {
        sym: data
        for sym, data in cache.items()
        if data.get("last_mentioned", "0000-00-00") >= cutoff_date
    }
    expired_count = before_count - len(cache)
    if expired_count > 0:
        print(f"[股票池] 移除了 {expired_count} 只超过 {max_age_days} 天未被提及的股票")

    _save_cache(cache)
    return sorted(cache.keys())


def _load_cache() -> dict:
    """读取缓存文件。如果不存在或损坏，返回空字典。"""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict) -> None:
    """把缓存写入文件。"""
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False, sort_keys=True)


def cache_status() -> dict:
    """
    返回当前缓存状态（调试用）。
    返回：{"total": N, "oldest": "2025-03-03", "newest": "2026-03-03"}
    """
    cache = _load_cache()
    if not cache:
        return {"total": 0, "oldest": None, "newest": None}

    dates = [v["last_mentioned"] for v in cache.values() if "last_mentioned" in v]
    return {
        "total": len(cache),
        "oldest": min(dates) if dates else None,
        "newest": max(dates) if dates else None,
    }
