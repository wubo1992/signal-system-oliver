"""
scripts/build_security_types.py — 生成证券类型表 data/cache/security_types.json

Nasdaq screener 接口返回的 name 字段带完整证券全称（含证券类别），
用它把代码分成 普通股 / ETF / 权证 / 单位 / 权 rights / 优先股 / 债券，
供 oneil_rs.py 剔除「非普通股」，避免权证动辄数倍的涨幅把普通股挤到评级底部。

关键：必须用【词边界】匹配，不能用子串匹配。
  - 子串 'right' 会误伤 "…(each representing the right to receive…)"（AMX 是 ADR）
  - 子串 'trust' 会把 REIT（"American Assets Trust Inc. Common Stock"）误判成 ETF
  - "American Depositary Shares" 是 ADR（普通股），不是优先股
所以优先级最高的是先豁免 ADR，再判类别。

用法：
    uv run python scripts/build_security_types.py
"""

import json
import re
from collections import Counter
from pathlib import Path

import requests

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
OUT_FILE = CACHE_DIR / "security_types.json"

API_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=10000&offset=0&download=true"
)
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}

# 按顺序匹配，命中即定；全部不命中 → common
_EXCLUDE_RULES: list[tuple[str, str]] = [
    (r"\bWarrants?\b", "warrant"),
    (r"\bRights?\b", "right"),
    (r"\bUnits?\b", "unit"),
    (r"Preferred (Stock|Shares)", "preferred"),
    (r"Senior Notes|Notes Due|Subordinated Notes|Debentures", "note"),
]


def classify(name: str) -> str:
    """按证券全称判定类别。

    ADR（American Depositary Shares / Receipts）代表普通股权益，一律按 common。

    ⚠️ 「depositary」不能作为 ADR 的判据 —— 优先股也以凭证形式发行，叫
    「Depositary Shares each representing 1/1000th of a 4.25% Series A
    Cumulative Redeemable Preferred Stock」。只写 `if "depositary" in name`
    会把 198 只优先股误判成普通股（其中 62 只已有行情数据，正在污染 RS 横截面）。
    所以 ADR 豁免必须同时满足：全称里有 "American Depositary" / "Depositary Receipt"，
    且全称里没有 "Preferred"。
    """
    lowered = name.lower()
    if "preferred" not in lowered and (
        "american depositary" in lowered or "depositary receipt" in lowered
    ):
        return "common"
    for pattern, kind in _EXCLUDE_RULES:
        if re.search(pattern, name, re.IGNORECASE):
            return kind
    return "common"


def main() -> None:
    resp = requests.get(API_URL, headers=HEADERS, timeout=90)
    resp.raise_for_status()
    rows = resp.json()["data"]["rows"]

    types = {
        row["symbol"].upper().strip(): {
            "name": row["name"],
            "kind": classify(row["name"]),
        }
        for row in rows
    }
    OUT_FILE.write_text(json.dumps(types, ensure_ascii=False), encoding="utf-8")

    counts = Counter(meta["kind"] for meta in types.values())
    print(f"已写入 {OUT_FILE}（{len(types)} 个代码）")
    print(f"分类分布: {dict(counts)}")
    print(f"排除（非普通股）合计: {sum(v for k, v in counts.items() if k != 'common')}")


if __name__ == "__main__":
    main()