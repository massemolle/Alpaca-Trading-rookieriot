"""Budget-slot guidance for the judge (2026-09-14): the journal repeatedly
used slot availability as a PRO-trade argument — cycle 197 opened SPY at
signal strength 0.052 ("with the last budget slot the clean-book, best-payout
candidate is the disciplined pick") after refusing SPY at 0.165 (cycle 195,
"simply too weak to open on conviction") and 0.034 (cycle 196, "near-noise");
2026-09-08 cycle 135 added a third XLK spread the same way. The prompt taught
nothing about how `remaining_budget` should bear on selectivity. These tests
pin the new guidance and guard the prompt sections the pipeline depends on."""
from __future__ import annotations

import llm_reasoner


def test_prompt_teaches_budget_is_ceiling_not_reason():
    # The lever for the cycle-197-class pattern; if the bullet is dropped or
    # reworded away from its point, this fails and the change must be argued.
    assert "`remaining_budget` is a ceiling, never a reason" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_rejects_best_of_weak_slate_as_justification():
    assert "best of a weak slate" in llm_reasoner.SYSTEM_PROMPT
    assert "does not become acceptable because the alternatives are worse" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_keeps_json_contract_verbatim():
    # _decide_via_claude_code and the openai path both parse exactly this shape.
    assert '{"selected": ["TICKER", ...], "reasoning": "..."}' in llm_reasoner.SYSTEM_PROMPT


def test_prompt_keeps_citation_rule():
    # D10 provenance: _check_citations depends on the bracket-citation habit.
    assert "cite its fact id in square brackets" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_keeps_abstention_and_stacking_guidance():
    # The 09-02 book-facts bullet and the abstention line must survive edits
    # to the neighboring budget bullet.
    assert "Skipping a mediocre setup is a valid, often correct, decision." in llm_reasoner.SYSTEM_PROMPT
    assert "_OPEN_SPREADS" in llm_reasoner.SYSTEM_PROMPT
