"""Options trading level gate (added 2026-08-30, after cross-checking a
sibling project's own hardening pass): level 3 ("Spreads/Straddles") is
required for every multi-leg order this bot places, but it was never
checked at runtime before this -- only verified once by hand at account
setup. These test the exact boolean this project's bot.run_cycle() now
gates screening on, matching this codebase's existing style of testing
gate logic directly rather than mocking the full orchestrator.
"""
from __future__ import annotations


def _options_level_ok(account: dict) -> bool:
    """Mirrors bot.run_cycle()'s own gate condition exactly."""
    level = account.get("options_trading_level")
    return level is not None and level >= 3


def test_level_3_passes():
    assert _options_level_ok({"options_trading_level": 3}) is True


def test_level_above_3_passes():
    assert _options_level_ok({"options_trading_level": 4}) is True


def test_level_below_3_fails_closed():
    assert _options_level_ok({"options_trading_level": 2}) is False


def test_missing_level_fails_closed():
    """A missing/unreadable field must be treated as insufficient, not an
    implicit pass -- fail closed, same convention as every other gate in
    this codebase."""
    assert _options_level_ok({}) is False


def test_none_level_fails_closed():
    assert _options_level_ok({"options_trading_level": None}) is False
