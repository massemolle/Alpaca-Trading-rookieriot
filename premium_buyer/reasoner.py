"""The buyer's judge — same headless-Claude contract as the credit bot's
reasoner, with a debit-side prompt and a REQUIRED stated probability per
pick (feeds the rhetoric audit and Brier scoring). Abstains on any failure."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the decision layer of a LONG-PREMIUM options sleeve \
(buy calls on 'long' signals, puts on 'short'). Candidates already passed code \
gates: liquidity, DTE 5-14, premium cap, and a fair-price check — \
[*_PRICE_RATIO] <= 1.4 means the option costs at most 1.4x its Black-Scholes \
value at realized volatility (cheap premium is the entire edge thesis).

Rules:
- Select zero, one, or at most `remaining_budget` candidates. Abstaining is \
often correct: buying premium bleeds theta daily, so only conviction in a \
MOVE justifies a pick.
- For EVERY pick you must state `p_move`: your probability (0-1) that the \
underlying moves at least 1% in the signal direction before expiry. Never \
select with p_move below 0.55 — that would contradict your own belief.
- Cite a fact id in square brackets for every number you use, exactly as \
provided. Never invent numbers.

Respond ONLY with JSON: {"selected": [{"ticker": str, "p_move": float}, ...], \
"reasoning": "a few real sentences with [FACT_ID] citations"}."""


def decide(candidates: list[dict], remaining_budget: int) -> dict:
    if not candidates:
        return {"selected": [], "reasoning": "No candidates this cycle."}
    prompt = (SYSTEM_PROMPT + "\n\nRespond with ONLY the JSON object.\n\n"
              + json.dumps({"remaining_budget": remaining_budget, "candidates": candidates},
                           default=str))
    cmd = ["claude", "-p", prompt, "--output-format", "text"]
    model = os.environ.get("REASONER_CLAUDE_MODEL")
    if model:
        cmd += ["--model", model]
    try:
        with tempfile.TemporaryDirectory() as scratch:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=400, cwd=scratch)
        if res.returncode != 0:
            raise RuntimeError(res.stderr.strip()[:200])
        text = res.stdout.strip()
        if text.startswith("```"):
            text = text.strip("`\n")
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text)
        assert isinstance(parsed.get("selected"), list)
        assert isinstance(parsed.get("reasoning"), str)
        for s in parsed["selected"]:
            assert isinstance(s, dict) and "ticker" in s
        return parsed
    except Exception:
        logger.exception("premium reasoner failed — abstaining")
        return {"selected": [], "reasoning": "Reasoner failed; no trade (fail-safe abstention)."}
