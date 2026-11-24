"""One bot run must write exactly one cycles row, and keep its error.

Live evidence 2026-11-24, cycles 1065/1066: the judge's first 2-pick
selection since the p_win tune opened SPY at 16:31:17 and GLD at 16:31:20
in ONE bot run — but `db.record_cycle` sat inside the per-pick open loop,
so each executed pick wrote its own cycle row. The decision journal, menu
book, shadow book and credit forecasts all attached to the LAST id (1066),
leaving 1065 a journal-less phantom: `analyze-regret`'s "pull the journal
entry for that cycle_id" dead-ends on it, and judged-cycle counts inflate
by one per extra pick.

The companion defect: once the first successful open created the row, the
post-loop `if cycle_id is None` recorder never ran again — so a failure on
a LATER pick set `error_text` and then dropped it. The row read "opened",
error null, and only bot.log knew.

Pinned here:
- the in-loop "opened" record_cycle call is guarded by `if cycle_id is None`;
- bot.py has exactly one "opened" record_cycle call site;
- a late-pick error is persisted via db.update_cycle_error;
- db.update_cycle_error issues an UPDATE on the cycles table of the
  configured schema with (error, cycle_id) parameters.
"""
from __future__ import annotations

import inspect
import re
from contextlib import contextmanager

import bot
import db


def _run_cycle_source() -> str:
    return inspect.getsource(bot.run_cycle)


def test_opened_record_cycle_is_guarded():
    src = _run_cycle_source()
    assert re.search(
        r'if cycle_id is None:\s*\n\s*cycle_id = db\.record_cycle\(slim_candidates, "opened"',
        src,
    ), "the in-loop record_cycle call must only run once per bot run"


def test_single_opened_call_site():
    src = _run_cycle_source()
    calls = re.findall(r'db\.record_cycle\(slim_candidates, "opened"', src)
    assert len(calls) == 1, "exactly one 'opened' cycle-row call site expected"


def test_late_pick_error_is_persisted():
    src = _run_cycle_source()
    idx = src.find("elif error_text is not None:")
    assert idx != -1, "post-loop branch for a late-pick error is missing"
    tail = src[idx : idx + 500]
    assert "db.update_cycle_error(cycle_id, error_text)" in tail


class _FakeCursor:
    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _fake_connection(cursor):
    @contextmanager
    def fake():
        yield _FakeConn(cursor)

    return fake


def test_update_cycle_error_sql(monkeypatch):
    cur = _FakeCursor()
    monkeypatch.setattr(db, "_connection", _fake_connection(cur))
    db.update_cycle_error(123, "RuntimeError: boom")
    assert len(cur.executed) == 1
    sql, params = cur.executed[0]
    norm = " ".join(sql.split()).lower()
    assert norm.startswith("update")
    assert ".cycles set error = %s where id = %s" in norm
    assert params == ("RuntimeError: boom", 123)


def test_update_cycle_error_targets_configured_schema(monkeypatch):
    cur = _FakeCursor()
    monkeypatch.setattr(db, "_connection", _fake_connection(cur))
    db.update_cycle_error(7, "x")
    sql, _ = cur.executed[0]
    assert f"{db._schema()}.cycles" in sql
