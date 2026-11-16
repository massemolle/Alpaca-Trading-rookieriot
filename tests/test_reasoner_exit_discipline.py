"""Exit-discipline guidance for the judge (2026-11-16): the journal repeatedly
computed break-even win rates against MAX_LOSS as if spreads were held to
expiry — c964 "requiring a ~96% win rate just to break even", c962 "a ~27:1
loss-to-gain profile", c963 "$15 credit on $485 max loss is a ~3% reward for
real tail risk" — while the book's coded exits (risk_gate.should_close) cap
the typical loss near 1x credit (stop at 2x cost-to-close) and take profit at
50% captured, making break-even ~2/3 for every candidate regardless of credit
size. The prompt now teaches the actual payoff, interpolated FROM config so it
can never contradict the live exit parameters. These tests pin that wiring."""
from __future__ import annotations

import llm_reasoner
from config import config


def test_prompt_states_the_configured_exit_parameters():
    # Interpolated, not hardcoded: a config change must flow into the prompt.
    assert f"{config.risk.profit_target_pct:.0%} of the credit is captured" \
        in llm_reasoner.SYSTEM_PROMPT
    assert f"{config.risk.stop_loss_multiple:g}x the credit received" \
        in llm_reasoner.SYSTEM_PROMPT


def test_prompt_states_the_exit_adjusted_break_even():
    loss_mult = config.risk.stop_loss_multiple - 1
    breakeven = loss_mult / (config.risk.profit_target_pct + loss_mult)
    assert f"break-even win rate is roughly {breakeven:.0%}" \
        in llm_reasoner.SYSTEM_PROMPT


def test_prompt_frames_max_loss_as_tail_not_expected_loss():
    # The lever for the c964-class pattern: max loss must be framed as the
    # tail scenario, never the denominator of a break-even computation.
    assert "`{TICKER}_MAX_LOSS` is the tail outcome" in llm_reasoner.SYSTEM_PROMPT
    assert "never to compute break-even win rates" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_warns_fat_credit_means_closer_to_the_money():
    # The flip side (c959 took the near-money QQQ bull put as "best
    # risk/reward"): a high credit-to-max-loss ratio alone is not a merit.
    assert "closer to the money (a LOWER p_win)" in llm_reasoner.SYSTEM_PROMPT


def test_prompt_keeps_citation_hygiene_for_derived_exit_numbers():
    # rhetoric.audit_values flags any `number [FACT_ID]` group whose number
    # deviates from the handed fact; a judge writing "+$22 [GLD_CREDIT_EST]"
    # (0.5x of a $44 credit) would be false-blocked (c601 class). The prompt
    # must steer derived exit outcomes into multiples, not dollar figures.
    assert "multiples of the credit" in llm_reasoner.SYSTEM_PROMPT
    assert "not as new dollar figures" in llm_reasoner.SYSTEM_PROMPT
