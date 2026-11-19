"""p_win anchoring guidance for the judge (2026-11-19): after D28 fixed the
exit arithmetic, the journal's abstentions still derived p_win almost
entirely from `strength` — c996 "0.352 is still only a modest screening
signal and I do not have conviction it reaches the ~67% win rate", c1001
"the slate is uniformly weak against the ~67% break-even win rate", c1011
"strength 0.407 ... pulls my honest p_win to roughly the break-even line" —
while resolved menu rows showed the dropped direction-aligned bear calls
going 57-0 over 11-18..11-19 (and 46-0 the day before). `strength` is a
0-1 conviction score from the screening layer, not a probability; the win
probability of a far-OTM short vertical is mostly structural (how far the
underlying must travel within DTE). The prompt now anchors p_win on
structure, keeps the signal as an adjustment, and reserves abstention for
direction conflicts, near-money fat credits, vol-vs-distance, and stacking.
These tests pin that guidance."""
from __future__ import annotations

import llm_reasoner


def test_prompt_anchors_pwin_on_structure_before_signal():
    assert "anchor it on the spread's STRUCTURE first" in llm_reasoner.SYSTEM_PROMPT
    assert "not the other way around" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_says_strength_is_not_a_win_probability():
    # The c996/c1001/c1011 lever: a conviction score must not be read as p_win.
    assert "it is not a win \nprobability".replace("\n", "") \
        in llm_reasoner.SYSTEM_PROMPT.replace("\n", "")
    assert 'Do not translate "strength below ~0.5" into "p_win below break-even"' \
        in llm_reasoner.SYSTEM_PROMPT


def test_prompt_frames_mean_reversion_as_haircut_not_veto():
    # c1011/c1001/c995 dropped trending direction-aligned spreads on an
    # oversold/lower-Bollinger read alone; the counter-move still has to reach
    # the short strike within DTE to hurt.
    assert "a p_win haircut, not an automatic veto" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_keeps_legitimate_abstention_reasons():
    # Calibration fix must not become action bias: direction conflicts,
    # near-money fat credits, vol-vs-distance, and stacking still abstain.
    assert "a signal pointing against the \nspread's direction".replace("\n", "") \
        in llm_reasoner.SYSTEM_PROMPT.replace("\n", "")
    assert "stacking a thesis the book already holds" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_still_requires_pwin_statement():
    # The guidance sits next to, and must not displace, the p_win contract.
    assert "you must also state `p_win`" in llm_reasoner.SYSTEM_PROMPT
    assert "contradicts your own belief" in llm_reasoner.SYSTEM_PROMPT
