"""
scripts/expand_universe.py — 扩充本地行情缓存，扩大 O'Neil RS 横截面股票池

为什么需要这个：
    O'Neil RS Rating 是【横截面】指标 —— 个股的 0.4×ROC(63) + 0.2×ROC(126)
    + 0.2×ROC(189) + 0.2×ROC(252) 加权分在【全市场所有股票】里排 1-99 百分位。
    横截面越大，排名越贴近 O'Neil 原版「在几千只股票里排序」的口径。
    当前本地只有 ~300 只，百分位区分度不足（大量并列、门槛失真）。

本脚本做什么：
    从 data/cache/nasdaq_market_caps.json（约 6700 个代码）筛出市值达标的股票，
    下载日线到 data/cache/{symbol}.pkl，使 oneil_rs.compute_oneil_rs_map 的
    横截面样本从 ~300 扩到 ~2000-3000 只。

用法：
    uv run python scripts/expand_universe.py --dry-run     # 只看会下载哪些，不下载
    uv run python scripts/expand_universe.py               # 下载市值 >= 10 亿美元
    uv run python scripts/expand_universe.py --min-cap 3e9 # 更严格的市值门槛
    uv run python scripts/expand_universe.py --limit 500   # 只取市值最大的 500 只试跑

注意：
    * 只下载【本地缺失或历史不足】的，已有数据的直接跳过，不会覆盖现有缓存
    * 需要 253 根以上 K 线才能算 RS，所以 history_days 取 420（约 290 个交易日）
    * 下载走 Yahoo Finance，批量太快会触发 403，批次之间有 sleep
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from pathlib import Path

# 确保项目根目录在 path 里
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.fetcher import fetch  # noqa: E402

# 本地行情缓存目录（与 data/fetcher.CACHE_DIR 一致）
CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"

# 市值来源：约 6700 个美股代码 + 市值（美元）
MARKET_CAP_FILE = CACHE_DIR / "nasdaq_market_caps.json"

# 算 RS 至少需要 253 根 K 线，取 420 自然日 ≈ 290 个交易日，留足余量
HISTORY_DAYS = 420
_MIN_BARS = 253

# 排除的代码（非个股 / 已被 oneil_rs._NON_STOCK 覆盖 / 明显的类别股后缀）
_EXCLUDE = frozenset({
    "SPY", "QQQ", "IWM", "DIA", "VTI", "VOO", "XLK", "XLF", "XLE", "XLV",
    "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC", "VIX", "^VIX",
})

# 权证 / 单位 / 优先股 / 债券的识别【已改由 data/cache/security_types.json 承担】
# （见 scripts/build_security_types.py，用 Nasdaq 接口的证券全称判定）。
#
# 这里曾有一个按代码后缀的黑名单（WT/WS/UW/UN/RT/RF/…），已删除。
# 它把大量真实普通股误杀了 —— 误杀的不只是小票：
#   RF   Regions Financial      $23.8B   ← 因结尾 RF
#   NWS  News Corp Class B      $15.9B
#   CART Maplebear (Instacart)   $9.5B
#   FRT  Federal Realty         $9.3B
#   BRT  BRT Apartments          $0.27B  ← 因结尾 RT
#   FLWS 1-800-FLOWERS           $0.21B  ← 因结尾 WS
#   STRT STRATTEC                $0.34B
# 代码后缀无法区分「权证」和「恰好以 W/RT 结尾的普通股」，必须用权威字段。
_BAD_PREFIXES = ("$",)


def _normalize(symbol: str) -> str:
    """Yahoo 用 - 表示股份类别：BRK/A → BRK-A。"""
    return symbol.upper().strip().replace("/", "-")


def _has_enough_bars(symbol: str) -> bool:
    """本地已有 ≥253 根 K 线则跳过。"""
    f = CACHE_DIR / f"{symbol}.pkl"
    if not f.exists():
        return False
    try:
        with open(f, "rb") as fh:
            df = pickle.load(fh)
        return df is not None and len(df) >= _MIN_BARS
    except Exception:
        return False


def load_universe(min_cap: float) -> list[str]:
    """从 nasdaq_market_caps.json 读出市值达标的代码列表。"""
    if not MARKET_CAP_FILE.exists():
        raise SystemExit(
            f"[错误] 找不到市值文件：{MARKET_CAP_FILE}\n"
            f"       需要先用 data/fetcher 或 update_universe_sp500.py 生成。"
        )

    with open(MARKET_CAP_FILE, encoding="utf-8") as f:
        caps: dict = json.load(f)

    picked: list[tuple[str, float]] = []
    for symbol, cap in caps.items():
        symbol = _normalize(symbol)
        if not symbol or symbol in _EXCLUDE:
            continue
        if any(symbol.startswith(p) for p in _BAD_PREFIXES):
            continue
        if not isinstance(cap, (int, float)) or cap < min_cap:
            continue
        picked.append((symbol, float(cap)))

    # 市值降序 —— 先下大票，保证即使中途中断也覆盖了最重要的部分
    picked.sort(key=lambda x: -x[1])
    return [s for s, _ in picked]


def main() -> None:
    parser = argparse.ArgumentParser(description="扩充本地行情缓存以扩大 O'Neil RS 横截面")
    parser.add_argument(
        "--min-cap", type=float, default=1e9,
        help="市值门槛（美元），默认 10 亿。调高可减少下载量",
    )
    parser.add_argument(
        "--limit", type=int, default=0,
        help="只取市值最大的前 N 只（0 = 不限）",
    )
    parser.add_argument(
        "--batch", type=int, default=50,
        help="每批下载数量，默认 50",
    )
    parser.add_argument(
        "--sleep", type=float, default=2.0,
        help="批次之间的间隔秒数，默认 2.0（太快会触发 Yahoo 403）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只打印将要下载的股票，不实际下载",
    )
    args = parser.parse_args()

    universe = load_universe(args.min_cap)
    print(f"市值 ≥ {args.min_cap/1e9:.1f}B 的代码：{len(universe)} 只")
    if args.limit:
        universe = universe[:args.limit]
        print(f"应用 --limit {args.limit} → {len(universe)} 只")

    print(f"逐只检查本地缓存（需要 ≥{_MIN_BARS} 根 K 线）...")
    missing = [s for s in universe if not _has_enough_bars(s)]
    print(f"需要下载：{len(missing)} 只（已有 {len(universe) - len(missing)} 只）")

    if not missing:
        print("全部已有足够历史，无需下载。")
        return

    if args.dry_run:
        print(f"\n[dry-run] 前 30 只待下载：")
        for s in missing[:30]:
            print(f"  {s}")
        if len(missing) > 30:
            print(f"  ... 还有 {len(missing) - 30} 只")
        print("\n[dry-run] 未执行任何下载。去掉 --dry-run 开始下载。")
        return

    total_batches = (len(missing) + args.batch - 1) // args.batch
    success, failed = 0, []

    print(f"\n开始分批下载（{args.batch} 只/批，共 {total_batches} 批，间隔 {args.sleep}s）...")
    t0 = time.time()

    for i in range(0, len(missing), args.batch):
        batch = missing[i:i + args.batch]
        batch_num = i // args.batch + 1
        print(f"[{batch_num}/{total_batches}] {len(batch)} 只...", end="", flush=True)

        result = fetch(batch, history_days=HISTORY_DAYS)

        got = 0
        for sym in batch:
            df = result.get(sym)
            if df is not None and not df.empty and len(df) >= _MIN_BARS:
                success += 1
                got += 1
            else:
                failed.append(sym)

        elapsed = time.time() - t0
        rate = success / elapsed if elapsed > 0 else 0
        eta = (len(missing) - i - len(batch)) / rate if rate > 0 else 0
        print(f"  成功 {got}/{len(batch)} | 累计 {success} | 失败 {len(failed)}"
              f" | 预计剩余 {eta/60:.0f} 分钟")

        if i + args.batch < len(missing):
            time.sleep(args.sleep)

    print(f"\n{'=' * 55}")
    print(f"下载完成：成功 {success} 只，失败 {len(failed)} 只，"
          f"耗时 {(time.time() - t0)/60:.1f} 分钟")

    if failed:
        fail_file = Path("data/expand_universe_failed.txt")
        fail_file.write_text("\n".join(failed), encoding="utf-8")
        print(f"失败列表：{fail_file}")

    # 验证横截面规模
    from strategies.v_oliver_kell.oneil_rs import compute_oneil_rs_map
    rs_map = compute_oneil_rs_map({}, cache_dir=CACHE_DIR)
    ratings = [r for r, _ in rs_map.values() if r is not None]
    print(f"\n[横截面] O'Neil RS 有效样本：{len(ratings)} 只")
    if ratings:
        print(f"           评级区间 {min(ratings)} - {max(ratings)}，中位数 {sorted(ratings)[len(ratings)//2]}")


if __name__ == "__main__":
    main()