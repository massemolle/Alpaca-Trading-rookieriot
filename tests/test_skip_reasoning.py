"""The journaled skip reason must name the operative condition.

2026-09-07 (Labor Day, market closed all day): with the contest window still
latched, every morning cycle journaled "No new positions: contest deadline …
any spread opened now would be force-closed on the next cycle" — implying
entries were being actively suppressed on a day when nothing could trade at
all. bot._skip_reasoning pins the precedence: options-level alarm (operator
misconfiguration) first, then the closed market, then the entry suppressions
in gate order, then the concurrent-spread cap. The actual trade gating
(run_cycle's single `if`, which requires ALL conditions) is unaffected —
this is journal truthfulness only.

2026-09-15 (book at the 8-cap all day): every market-hours cycle fell
through to "No eligible candidates this cycle" although screening never ran
— the operative reason was zero remaining budget. The at-cap branch pins
that case; it sits last among the suppressions because the others are
time-bounded external events worth naming even on a full book.
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
        remaining_budget=3,
        open_spread_count=5,
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


def test_at_cap_names_the_cap_not_eligibility():
    # The exact 2026-09-15 misattribution, pinned: open market, nothing else
    # blocking, book full — the journal must say the cap, not imply an empty
    # funnel that never ran.
    r = reasoning(remaining_budget=0, open_spread_count=8)
    assert "concurrent-spread cap" in r
    assert "8 open" in r
    assert "Exits stay active" in r
    assert "No eligible candidates" not in r


def test_closed_market_outranks_cap():
    # 2026-09-15 20:00Z cycle: at cap AND market just closed — closed wins.
    r = reasoning(remaining_budget=0, open_spread_count=8, market_open=False)
    assert r.startswith("Market is closed")


def test_suppressions_outrank_cap():
    # Time-bounded external events stay visible even on a full book.
    assert reasoning(
        remaining_budget=0, open_spread_count=8,
        blackout=True, blackout_reason="FOMC blackout",
    ).startswith("No new positions: FOMC blackout")
    assert "protections" in reasoning(
        remaining_budget=0, open_spread_count=8, prot=HALTED
    )
    assert "force-closed on the next cycle" in reasoning(
        remaining_budget=0, open_spread_count=8,
        close_window=True,
        close_window_reason="contest deadline is within 2 hours",
    )


def test_cap_lowered_below_open_count_still_names_cap():
    # If the operator lowers MAX_CONCURRENT_SPREADS mid-flight the count can
    # exceed the cap; remaining_budget is clamped to 0 upstream — same branch.
    r = reasoning(remaining_budget=0, open_spread_count=9)
    assert "concurrent-spread cap" in r
    assert "9 open" in r
