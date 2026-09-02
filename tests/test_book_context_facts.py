"""Book-context facts for the judge (2026-09-02): six identical QQQ 725/730
bear calls were stacked in one day (cycles 53, 54, 62, 63, 65, 66), each
cycle's reasoning claiming budget restraint — the fact packet contained no
book state, so the judge could not know it was re-buying the same position.
These tests pin the {TICKER}_OPEN_SPREADS / {TICKER}_OPEN_MAX_LOSS facts and
their coupling to the reasoner prompt."""
from __future__ import annotations

import re

import bot
import llm_reasoner

AS_OF = "2026-09-02T19:30:00+00:00"


def _facts(tkr, counts, exposure):
    return {f["fact_id"]: f for f in bot._book_context_facts(tkr, AS_OF, counts, exposure)}


def test_held_underlying_reports_count_and_exposure():
    facts = _facts("QQQ", {"QQQ": 6, "SPY": 1}, {"QQQ": 2509.999, "SPY": 436.5})
    assert facts["QQQ_OPEN_SPREADS"]["value"] == 6
    assert facts["QQQ_OPEN_MAX_LOSS"]["value"] == 2510.0  # rounded to cents


def test_unheld_underlying_reports_zero():
    facts = _facts("XLK", {"QQQ": 6}, {"QQQ": 2510.0})
    assert facts["XLK_OPEN_SPREADS"]["value"] == 0
    assert facts["XLK_OPEN_MAX_LOSS"]["value"] == 0.0


def test_facts_carry_full_provenance():
    # D10: every packet fact has provenance; missing keys would break the
    # journal/dashboard contract the other seven facts follow.
    for fact in bot._book_context_facts("QQQ", AS_OF, {}, {}):
        assert set(fact) == {"fact_id", "value", "as_of", "source", "quality", "derivation"}
        assert fact["as_of"] == AS_OF
        assert fact["source"] == "db.open_spreads"
        assert fact["quality"] == "computed"


def test_fact_ids_are_citable():
    # _check_citations extracts [A-Z0-9_.]+ — the new ids must match, or every
    # legitimate citation would log a spurious unknown-fact warning.
    pattern = re.compile(r"^[A-Z0-9_.]+$")
    for fact in bot._book_context_facts("QQQ", AS_OF, {}, {}):
        assert pattern.match(fact["fact_id"])


def test_prompt_names_both_book_facts():
    # The prompt teaches the judge what the facts mean; if the facts are ever
    # renamed or dropped, the prompt guidance must move with them.
    assert "_OPEN_SPREADS" in llm_reasoner.SYSTEM_PROMPT
    assert "_OPEN_MAX_LOSS" in llm_reasoner.SYSTEM_PROMPT
