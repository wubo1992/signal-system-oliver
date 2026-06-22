"""
strategies/base.py — 策略抽象基类

所有策略都必须继承此类并实现 run_date() 方法。

使用方式：
    class MyStrategy(StrategyBase):
        strategy_id = "my_strategy"
        strategy_name = "我的策略"

        def run_date(self, date, queue):
            ...
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone

import pandas as pd

from events.queue import EventQueue


class StrategyBase(ABC):
    """
    策略基类。

    类属性（子类必须覆盖）：
        strategy_id:   策略唯一标识符，用于输出文件夹命名，如 "v1_wizard"
        strategy_name: 策略显示名称，用于报告标题，如 "魔法师策略V1"
    """

    strategy_id: str = "base"
    strategy_name: str = "基础策略"

    def __init__(
        self,
        strategy_config: dict,
        market_data: dict[str, pd.DataFrame],
    ) -> None:
        """
        初始化策略。

        参数：
            strategy_config: 本策略专属的配置字典
                             （即 config["strategies"][strategy_id]，不是整个 config）
            market_data:     股票历史数据，key 为股票代码，value 为 DataFrame
        """
        self.cfg = strategy_config
        self.market_data = market_data

    @abstractmethod
    def run_date(self, date: datetime, queue: EventQueue) -> list:
        """
        对单个交易日运行策略，把产生的信号放入 queue。

        参数：
            date:  当前交易日（datetime，含时区）
            queue: 事件队列，调用 queue.put(signal_event) 发布信号

        返回：
            当天产生的信号列表（同时放入 queue）
        """
        ...

    def _slice_to_date(self, df: pd.DataFrame, date: datetime) -> pd.DataFrame:
        """切片到指定日期（含）"""
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        idx = df.index
        if idx.tzinfo is None:
            idx = idx.tz_localize("UTC")
            df = df.copy()
            df.index = idx
        return df[df.index < date + pd.Timedelta(days=1)]

    def _get_close_for_date(self, df: pd.DataFrame, date: datetime) -> float | None:
        """
        获取指定日期的收盘价。

        yfinance 对美股返回每日两个 bar（05:00 和 14:30 UTC），
        其中 14:30 UTC 的 bar 代表当日收盘交易。
        直接用 iloc[-1] 可能返回次日 05:00 的错误价格。

        修复：找到与 date 日历日期匹配的最后一个 bar。
        """
        row = self._get_row_for_date(df, date)
        if row is None:
            return None
        return float(row["close"])

    def _get_row_for_date(self, df: pd.DataFrame, date: datetime) -> pd.Series | None:
        """
        获取与 date 日历日期匹配的最后一行（包含 close, volume 等）。

        yfinance 对美股返回每日两个 bar（05:00 和 14:30 UTC），
        其中 14:30 UTC 的 bar 代表当日收盘交易。
        """
        df_sliced = self._slice_to_date(df, date)
        if df_sliced.empty:
            return None

        # 标准化 date 到日历日期（00:00:00）
        if date.tzinfo is not None:
            date_normalized = date.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            date_normalized = date.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)

        # 找到与 date 属于同一日历日（<= date_normalized + 1天）的最后一个 bar
        cutoff = date_normalized + pd.Timedelta(days=1)
        mask = df_sliced.index <= cutoff
        df_matched = df_sliced.loc[mask]
        if df_matched.empty:
            return df_sliced.iloc[-1]
        return df_matched.iloc[-1]

    def _get_prev_day_row(self, df: pd.DataFrame) -> pd.Series | None:
        """
        获取前一天的正确bar（修复双bar股票问题）。

        yfinance 对美股每天返回两个 bar（05:00 和 14:30 UTC），
        其中 14:30 的 bar 才是当天收盘，05:00 是次日盘前。
        直接用 iloc[-2] 可能取到当天盘前 bar 而非前一天收盘 bar。
        """
        if len(df) < 2:
            return None
        current_idx = df.index[-1]
        prev_day = current_idx.normalize() - pd.Timedelta(days=1)
        mask = df.index.normalize() == prev_day
        matches = df[mask]
        if len(matches) > 0:
            return matches.iloc[-1]
        return df.iloc[-2]  # fallback for single-bar stocks
