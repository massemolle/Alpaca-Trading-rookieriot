"""The concurrent cap must count each spread exactly once.

Cycle 413 (2026-10-01, 14:02Z): the LLM selected SPY and TLT with two slots
genuinely free. SPY opened and was recorded as a live DB row; the TLT check
then saw open_count_used = 8 on a 7-row live book — the just-recorded SPY
counted once via get_live_spreads() and again via opened_this_cycle — and
the gate rejected the judge's pick at a cap that was not actually reached.

The gate's contract (unchanged here): open_count = live DB rows + opens the
DB does not know about yet. The fix is in bot.py, which now passes only
UNRECORDED opens (nonzero solely while a DB write after submission has
failed), so the cap binds at exactly the configured number of real spreads.
"""
from __future__ import annotations

import asyncio
import dataclasses
import re
from pathlib import Path

import pretrade_gate
import risk_gate
from pretrade_gate import pre_trade_check
from tests.conftest import FakeClient, make_plan

from tests.test_pretrade_gate import make_mcp


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _pin_cap(monkeypatch, cap: int):
    # The live cap is env-tunable (D21); pin it so the test asserts counting
    # logic, not whatever the environment sets.
    pinned = dataclasses.replace(
        pretrade_gate.config,
        risk=dataclasses.replace(pretrade_gate.config.risk, max_concurrent_spreads=cap),
    )
    monkeypatch.setattr(pretrade_gate, "config", pinned)
    monkeypatch.setattr(risk_gate, "config", pinned)


def test_seven_live_rows_leave_the_eighth_slot_open(fake_db, monkeypatch):
    """The literal corrected cycle-413 shape: 7 live rows (the spread opened
    earlier this cycle already recorded among them), no unrecorded opens —
    the 8th slot is free and the gate must allow it."""
    _pin_cap(monkeypatch, 8)
    plan = make_plan()
    fake_db.extend(
        {"underlying": f"T{i}", "max_loss": 300.0, "contracts": 1} for i in range(7)
    )
    result = run(pre_trade_check(make_mcp(plan), FakeClient(), plan, opened_this_cycle=0))
    assert result.allowed, result.reasons
    assert result.facts["open_count_used"] == 7


def test_at_cap_still_blocks(fake_db, monkeypatch):
    """Cap integrity control: 8 live rows means no 9th spread."""
    _pin_cap(monkeypatch, 8)
    plan = make_plan()
    fake_db.extend(
        {"underlying": f"T{i}", "max_loss": 300.0, "contracts": 1} for i in range(8)
    )
    result = run(pre_trade_check(make_mcp(plan), FakeClient(), plan, opened_this_cycle=0))
    assert not result.allowed
    assert "concurrent" in result.reason


def test_unrecorded_open_still_counts(fake_db, monkeypatch):
    """The fail-closed compensation stands: an open the DB missed (write
    failed after submission) still occupies a slot at the gate."""
    _pin_cap(monkeypatch, 8)
    plan = make_plan()
    fake_db.extend(
        {"underlying": f"T{i}", "max_loss": 300.0, "contracts": 1} for i in range(7)
    )
    result = run(pre_trade_check(make_mcp(plan), FakeClient(), plan, opened_this_cycle=1))
    assert not result.allowed
    assert "concurrent" in result.reason
    assert result.facts["open_count_used"] == 8


def test_bot_passes_only_unrecorded_opens_to_the_gate():
    """Pin bot.py's counter wiring in source (idiom: test_live_book_truth
    pins the live-status SQL the same way).

    - every pre_trade_check call feeds the gate opened_unrecorded, never the
      journal counter opened_this_cycle;
    - the unrecorded counter increments with each submission and decrements
      only once the row is recorded, so a failed DB write keeps the slot
      occupied at the gate.
    """
    src = Path(__file__).resolve().parent.parent.joinpath("bot.py").read_text()
    gate_args = re.findall(r"opened_this_cycle=(\w+)", src)
    assert gate_args, "pre_trade_check call sites not found in bot.py"
    assert set(gate_args) == {"opened_unrecorded"}, gate_args
    assert src.count("opened_unrecorded += 1") == 1
    assert src.count("opened_unrecorded -= 1") == 1
    inc = src.index("opened_unrecorded += 1")
    record = src.index("db.record_spread_open(")
    dec = src.index("opened_unrecorded -= 1")
    assert inc < record < dec, "decrement must follow the successful DB write"
