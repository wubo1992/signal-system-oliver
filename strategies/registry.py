"""
strategies/registry.py — 策略注册表

添加新策略步骤：
    1. 在 strategies/ 下新建包：strategies/vN_xxx/
    2. 在包内实现继承 StrategyBase 的策略类
    3. 在下方 STRATEGY_REGISTRY 中添加一行：
           "vN": MyNewStrategy,
    4. 在 config.yaml 的 strategies: 下添加对应配置段

仅此而已，不需要改 main.py 或其他任何框架代码。
"""

from strategies.v_oliver_kell import OliverKellStrategy

# key   = --strategy 参数的值
# value = 策略类（继承 StrategyBase）
STRATEGY_REGISTRY: dict[str, type] = {
    "v_oliver_kell": OliverKellStrategy,
}

# 策略分类映射：CLI key -> 类别
STRATEGY_CATEGORIES: dict[str, str] = {
    "v_oliver_kell": "Oliver Kell",
}


def get_strategy(strategy_id: str) -> type:
    """
    根据 strategy_id 返回对应策略类。

    参数：
        strategy_id: 如 "v_eps_v2"

    返回：
        策略类（未实例化）

    异常：
        ValueError: strategy_id 不在注册表中
    """
    if strategy_id not in STRATEGY_REGISTRY:
        available = list(STRATEGY_REGISTRY.keys())
        raise ValueError(
            f"未知策略 '{strategy_id}'。"
            f"可用策略：{available}。"
            f"请在 strategies/registry.py 的 STRATEGY_REGISTRY 中注册新策略。"
        )
    return STRATEGY_REGISTRY[strategy_id]


def list_strategies() -> list[dict]:
    """返回所有已注册策略的信息列表。"""
    result = []
    for sid, cls in STRATEGY_REGISTRY.items():
        result.append({
            "id": sid,
            "strategy_id": cls.strategy_id,
            "name": cls.strategy_name,
            "category": STRATEGY_CATEGORIES.get(sid, "未分类"),
        })
    return result
