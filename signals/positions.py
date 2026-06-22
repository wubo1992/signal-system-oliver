"""
signals/positions.py — 持仓状态持久化

在两次 live 运行之间，将策略的持仓状态保存到 JSON 文件。
这样策略在下次运行时能继续追踪已持有仓位的出场条件
（固定止损 / 追踪止盈 / 时间止损）。

文件位置：
  - v_eps_v2: output/v_eps_v2/positions.json

持仓文件格式（不存储策略特定参数，由各策略动态计算）：
{
  "SYMBOL": {
    "symbol": "SYMBOL",
    "entry_price": 100.0,
    "entry_date": "2026-01-01T00:00:00+00:00",
    "highest_price": 110.0,
    "days_held": 10,
    "shares": 100   # 持仓股数，用户手动填写
  }
}

用户可以直接编辑此文件：
  - 删除某只股票的行 → 取消对该仓位的跟踪（你已手动平仓）
  - 修改 entry_price   → 调整为实际买入价（如果系统信号价和你的实际价不同）
  - 修改 highest_price → 更新追踪止盈的最高价
  - 修改 shares       → 更新持仓股数（重要！用于计算卖出建议）
  - 手动添加一行      → 跟踪你自己加仓或手动买入的股票
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Position:
    symbol: str
    entry_price: float
    entry_date: datetime
    highest_price: float
    days_held: int = 0
    shares: float = 0.0

OUTPUT_DIR = Path(__file__).parent.parent / "output"

# 各策略持仓文件路径（每个策略独立持仓）
# v_eps_v2: output/v_eps_v2/positions.json


def _positions_file(strategy_id: str) -> Path:
    """返回指定策略的持仓文件路径"""
    return OUTPUT_DIR / strategy_id / "positions.json"


def load_positions(strategy_id: str) -> dict[str, Position]:
    """
    从共享 positions.json 加载持仓。
    返回 {symbol: Position} 字典，供策略 _check_exits() 使用。

    注意：stop_loss 不再存储，由各策略根据自身参数动态计算。
    """
    path = _positions_file(strategy_id)
    if not path.exists():
        return {}

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    result: dict[str, Position] = {}
    for symbol, d in data.items():
        try:
            entry_date = datetime.fromisoformat(d["entry_date"])
            result[symbol] = Position(
                symbol=symbol,
                entry_price=float(d["entry_price"]),
                entry_date=entry_date,
                highest_price=float(d["highest_price"]),
                days_held=int(d.get("days_held", 0)),
                shares=float(d.get("shares", 0.0)),
            )
        except (KeyError, ValueError, TypeError):
            print(f"[持仓] 警告：{symbol} 数据格式错误，已跳过")

    return result


def save_positions(positions: dict[str, Position], strategy_id: str) -> None:
    """
    将策略当前持仓保存到共享 positions.json。
    每次 live 运行结束后调用，保存新买入 + 保留已卖出股票（不删除，数量不变）。

    注意：
    - 卖出后不删除记录，数量保持不变（等待用户手动确认平仓）
    - stop_loss 不再存储，由各策略根据自身参数动态计算。
    """
    path = _positions_file(strategy_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    # 先读取原有数据，保留已卖出股票的 shares 数量
    existing_data = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            existing_data = json.load(f)

    data = {}
    for sym, pos in positions.items():
        # 保留原有 shares（如果之前已卖出）
        if sym in existing_data and "shares" in existing_data[sym]:
            existing_shares = existing_data[sym]["shares"]
            # 如果原有 shares > 0 且当前是 0，说明已卖出，保留原数量
            if existing_shares > 0 and pos.shares == 0:
                shares_to_save = existing_shares
            else:
                shares_to_save = int(pos.shares) if pos.shares > 0 else 0
        else:
            shares_to_save = int(pos.shares) if pos.shares > 0 else 0

        data[sym] = {
            "symbol": pos.symbol,
            "entry_price": round(pos.entry_price, 4),
            "entry_date": pos.entry_date.isoformat(),
            "highest_price": round(pos.highest_price, 4),
            "days_held": pos.days_held,
            "shares": shares_to_save,
        }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
