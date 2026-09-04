"""Entry/exit symmetry around the contest deadline (2026-09-04 incident).

With CONTEST_END_UTC at 15:00 UTC, should_force_close fired on every open
spread from 13:00 UTC onward — but nothing blocked NEW entries, so each
cycle opened a spread that the next cycle force-closed at the cost of the
bid/ask spread (eight real round-trips, ≈ −$134 in one afternoon).

These tests pin the fix: risk_gate.in_contest_close_window() is True exactly
when should_force_close's contest trigger is live (including forever after
the deadline — the condition never un-latches), and bot.py skips screening
while it is True.
"""
import dataclasses
from datetime import date, datetime, timezone

import risk_gate


CONTEST_END = "2026-09-04T15:00:00+00:00"
FAR_EXPIRY = date(2026, 9, 14)  # 10 DTE from the incident day: no DTE trigger


def _pin_contest_end(monkeypatch, value: str = CONTEST_END) -> None:
    # Config dataclasses are frozen and CONTEST_END_UTC is env-tunable; the
    # nightly gate runs pytest with .env sourced, so pin the module-level
    # config reference (same idiom as test_pretrade_gate).
    pinned = dataclasses.replace(
        risk_gate.config,
        risk=dataclasses.replace(risk_gate.config.risk, contest_end_utc=value),
    )
    monkeypatch.setattr(risk_gate, "config", pinned)


def test_window_closed_before_minus_two_hours(monkeypatch):
    _pin_contest_end(monkeypatch)
    before = datetime(2026, 9, 4, 12, 59, tzinfo=timezone.utc)
    hit, reason = risk_gate.in_contest_close_window(before)
    assert not hit and reason is None


def test_window_opens_at_minus_two_hours(monkeypatch):
    _pin_contest_end(monkeypatch)
    boundary = datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc)
    hit, reason = risk_gate.in_contest_close_window(boundary)
    assert hit and "contest deadline" in reason


def test_window_never_unlatches_after_deadline(monkeypatch):
    """The exact 2026-09-04 afternoon state: hours past the deadline."""
    _pin_contest_end(monkeypatch)
    for after in (
        datetime(2026, 9, 4, 19, 30, tzinfo=timezone.utc),
        datetime(2026, 9, 5, 14, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 30, 14, 0, tzinfo=timezone.utc),
    ):
        hit, _ = risk_gate.in_contest_close_window(after)
        assert hit, f"window must stay latched at {after}"


def test_entry_block_matches_exit_trigger(monkeypatch):
    """Symmetry: whenever the contest trigger would force-close a far-dated
    spread, the entry window must be flagged too — and vice versa."""
    _pin_contest_end(monkeypatch)
    samples = [
        datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 12, 59, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 13, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 15, 0, tzinfo=timezone.utc),
        datetime(2026, 9, 4, 19, 30, tzinfo=timezone.utc),
    ]
    for now in samples:
        force, _ = risk_gate.should_force_close(expiration=FAR_EXPIRY, now_utc=now)
        window, _ = risk_gate.in_contest_close_window(now)
        assert force == window, f"entry/exit asymmetry at {now}"


def test_dte_trigger_untouched(monkeypatch):
    """Expiration tomorrow still force-closes even far outside the window."""
    _pin_contest_end(monkeypatch, "2026-12-31T15:00:00+00:00")
    now = datetime(2026, 9, 4, 14, 0, tzinfo=timezone.utc)
    force, reason = risk_gate.should_force_close(
        expiration=date(2026, 9, 5), now_utc=now,
    )
    assert force and "expiration" in reason
    window, _ = risk_gate.in_contest_close_window(now)
    assert not window
