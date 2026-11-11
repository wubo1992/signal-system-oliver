"""
tests/signals/test_markdown_tables.py

回归测试：报告 / 雷达里的触发原因不能带裸竖线，否则 Markdown 表格破行。
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from signals.oliver_kell_radar_report import _short_context
from signals.report import _md_cell, _short_summary


KELL_REASON = (
    "[EMA Crossback] Entry | [RS-10D] 1.0676 | [RS] 1.1412 | [RS-10W] 1.0016 "
    "| [Vol] 0.5x | [RS-Rating] 76 | [RS-Mult] 1.3689 "
    "| [EMA] 10=314.5, 20=309.4 | [Stage] ema_crossback "
    "| [WStage] Stage 3 做顶 · 3 顶部期（发展中）"
)


def test_md_cell_escapes_pipe():
    assert _md_cell("a | b") == "a \\| b"
    assert _md_cell(None) == "—"


def test_short_summary_never_returns_raw_reason():
    """没有 [VCP]/[突破]/[量能] 段时，摘要必须用策略标签而不是原始 reason。"""
    summary = _short_summary(KELL_REASON)
    assert "|" not in summary
    assert "EMA Crossback" in summary


def test_short_context_has_no_bare_pipe():
    """雷达的 Context 列必须是单列文本。"""
    ctx = _short_context(KELL_REASON)
    assert "|" not in ctx
    assert len(ctx) <= 100


def test_short_context_keeps_readable_values():
    """Context 不能退化成空串或只剩一个词。"""
    ctx = _short_context(KELL_REASON)
    assert "RS-10D 1.0676" in ctx
    assert "EMA Crossback" in ctx


def test_short_context_handles_empty_reason():
    assert _short_context("") == ""
