"""
tests/signals/test_log_generator.py

回归测试：v_oliver_kell 信号日志生成器
  - 读中文表头 + BOM 的 signals.csv
  - 观望归多头 / 做空归空头
  - 表格单元格没有裸竖线（否则冲破 Markdown 表格）
  - 头部写死策略名，旧头部能剥掉
  - 全量重建后日期倒序
"""
import csv
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from signals import log_generator as lg


HEADERS = [
    "日期", "股票", "信号", "强度(1-5)", "触发原因", "参考止损", "持仓股数",
    "RS (10D)", "RS (20D)", "RS (10W)", "量比", "RS评级", "RS倍数", "Weinstein阶段",
]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(HEADERS)
        writer.writerows(rows)


@pytest.fixture
def strategy_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(lg, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(lg, "SIGNALS_LOG_FILE", tmp_path / "SIGNALS_LOG.md")
    d = tmp_path / "v_oliver_kell"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _row(date="2026-11-11", sym="FDX", signal="买入", reason=None, stop="$310.03"):
    return [
        date, sym, signal, 4,
        reason or "[EMA Crossback] Entry | [RS-10D] 1.0676 | [Vol] 0.5x",
        stop, "—", "1.0676", "1.1412", "1.0016", "0.5x", "76", "1.3689",
        "Stage 3 做顶 · 3 顶部期",
    ]


def test_load_signals_reads_chinese_bom_header(strategy_dir):
    """中文表头 + BOM 必须能读出来（此前用 utf-8 读会静默返回空）。"""
    _write_csv(strategy_dir / "signals.csv", [_row()])

    longs, shorts = lg.load_signals_from_csv("v_oliver_kell", "2026-11-11")

    assert len(longs) == 1
    assert longs[0]["symbol"] == "FDX"
    assert longs[0]["signal"] == "买入"
    assert longs[0]["weinstein_stage"] == "Stage 3 做顶 · 3 顶部期"
    assert shorts == []


def test_watchlist_counts_as_long_and_short_as_short(strategy_dir):
    """观望归多头，做空归空头。"""
    _write_csv(strategy_dir / "signals.csv", [
        _row(sym="ASX", signal="观望"),
        _row(sym="TTD", signal="做空"),
    ])

    longs, shorts = lg.load_signals_from_csv("v_oliver_kell", "2026-11-11")

    assert [r["symbol"] for r in longs] == ["ASX"]
    assert [r["symbol"] for r in shorts] == ["TTD"]


def test_daily_section_has_no_bare_pipe_in_cells(strategy_dir):
    """触发原因里的 ' | ' 必须被转义，否则表格行会冲破列。"""
    _write_csv(strategy_dir / "signals.csv", [_row()])

    longs, shorts = lg.load_signals_from_csv("v_oliver_kell", "2026-11-11")
    section = lg.generate_daily_section("2026-11-11", longs, shorts)

    header_cols = None
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cols = len(stripped.replace("\\|", "\x00").split("|")) - 2
        if set(stripped.replace("|", "").replace("-", "").replace(" ", "")) == set():
            continue
        if header_cols is None:
            header_cols = cols
            continue
        assert cols == header_cols, f"破表行: {stripped}"


def test_stop_loss_is_rendered_as_is(strategy_dir):
    """CSV 里已经是 '$310.03'，不要再补 $（否则渲染成 '$$310.03'）。"""
    _write_csv(strategy_dir / "signals.csv", [_row(stop="$310.03")])

    longs, shorts = lg.load_signals_from_csv("v_oliver_kell", "2026-11-11")
    section = lg.generate_daily_section("2026-11-11", longs, shorts)

    assert "$$" not in section
    assert "$310.03" in section


def test_update_writes_header_with_strategy_and_strips_old_header(strategy_dir):
    """头部必须是 v_oliver_kell，旧的 '# 全策略信号汇总日志' 头要被剥掉。"""
    lg.SIGNALS_LOG_FILE.write_text(
        "# 全策略信号汇总日志\n\n> 旧头\n\n---\n\n## 2026-11-10\n\n旧的日期段落\n",
        encoding="utf-8",
    )
    _write_csv(strategy_dir / "signals.csv", [_row()])

    lg.update_signals_log("2026-11-11")

    content = lg.SIGNALS_LOG_FILE.read_text(encoding="utf-8")
    top_level = [ln for ln in content.splitlines() if ln.startswith("# ")]
    assert len(top_level) == 1
    assert content.startswith("# 信号汇总日志（v_oliver_kell）")
    assert "## 2026-11-11" in content
    assert "## 2026-11-10" in content  # 历史段落保留


def test_rebuild_orders_dates_descending(strategy_dir):
    """全量重建后日期倒序（最新的在顶部）。"""
    _write_csv(strategy_dir / "signals.csv", [
        _row(date="2026-11-09"),
        _row(date="2026-11-11"),
        _row(date="2026-11-10"),
    ])

    count = lg.rebuild_signals_log()

    assert count == 3
    content = lg.SIGNALS_LOG_FILE.read_text(encoding="utf-8")
    dates = [line[3:13] for line in content.splitlines() if line.startswith("## ")]
    assert dates == ["2026-11-11", "2026-11-10", "2026-11-09"]


def test_rebuild_matches_sequential_update_path(strategy_dir):
    """重建结果必须和逐日 update_signals_log（升序插入）逐字节一致。"""
    _write_csv(strategy_dir / "signals.csv", [
        _row(date="2026-11-09"),
        _row(date="2026-11-10"),
    ])

    lg.rebuild_signals_log()
    rebuilt = lg.SIGNALS_LOG_FILE.read_text(encoding="utf-8")

    lg.SIGNALS_LOG_FILE.unlink()
    lg.update_signals_log("2026-11-09")
    lg.update_signals_log("2026-11-10")
    sequential = lg.SIGNALS_LOG_FILE.read_text(encoding="utf-8")

    # 头部带「最后更新」时间戳，比较正文部分
    assert rebuilt.split("---", 1)[1] == sequential.split("---", 1)[1]
