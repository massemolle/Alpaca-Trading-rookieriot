"""The journaled skip reason must name the operative condition.

2026-09-07 (Labor Day, market closed all day): with the contest window still
latched, every morning cycle journaled "No new positions: contest deadline …
any spread opened now would be force-closed on the next cycle" — implying
entries were being actively suppressed on a day when nothing could trade at
all. bot._skip_reasoning pins the precedence: options-level alarm (operator
misconfiguration) first, then the closed market, then the entry suppressions
in gate order. The actual trade gating (run_cycle's single `if`, which
requires ALL conditions) is unaffected — this is journal truthfulness only.
"""
import bot
from protections import ProtectionResult

ALLOWED = ProtectionResult(allowed=True, reasons=[])
HALTED = ProtectionResult(
    allowed=False, reasons=["stop_streak: 6 stop-outs in the last 24h"]
)


def reasoning(**overrides):
    defaults = dict(
        options_level_ok=True,
        options_level=3,
        market_open=True,
        blackout=False,
        blackout_reason=None,
        prot=ALLOWED,
        close_window=False,
        close_window_reason=None,
    )
    defaults.update(overrides)
    return bot._skip_reasoning(**defaults)


def test_closed_market_outranks_contest_window():
    # The exact 2026-09-07 misattribution, pinned.
    r = reasoning(
        market_open=False,
        close_window=True,
        close_window_reason="contest deadline is within 2 hours",
    )
    assert r.startswith("Market is closed")


def test_closed_market_outranks_blackout_and_protections():
    r = reasoning(
        market_open=False, blackout=True, blackout_reason="FOMC blackout", prot=HALTED
    )
    assert r.startswith("Market is closed")


def test_options_level_alarm_outranks_everything():
    r = reasoning(options_level_ok=False, options_level=2, market_open=False)
    assert "Options trading level" in r


def test_open_market_suppressions_in_gate_order():
    assert reasoning(blackout=True, blackout_reason="FOMC blackout").startswith(
        "No new positions: FOMC blackout"
    )
    assert "protections" in reasoning(prot=HALTED)
    assert "force-closed on the next cycle" in reasoning(
        close_window=True,
        close_window_reason="contest deadline is within 2 hours",
    )


def test_open_market_nothing_blocking():
    assert reasoning() == "No eligible candidates this cycle."
