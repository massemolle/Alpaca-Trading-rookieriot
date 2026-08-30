---
name: tune-reasoner-prompt
description: Safely modify the day-trader LLM's system prompt (the "judge") in llm_reasoner.py when regret/ablation evidence shows a selection pattern problem. Use only after analyze-regret found a pattern.
---

# Tune the reasoner prompt

The judge = model + SYSTEM_PROMPT + facts. Only the prompt (and fact set) is
tunable here.

## Changeable
- Guidance on weighing specific facts (e.g. how to treat REALIZED_VOL vs CREDIT_EST).
- Abstention guidance phrasing (when to prefer no trade).
- Ordering/emphasis of decision criteria; added context the journal shows it
  repeatedly lacked (cite the cycles).

## NOT changeable (tests + gates depend on these)
- The JSON output contract (keys, types) — `_decide_via_claude_code` asserts it.
- The citation requirement (`[FACT_ID]` per number) and `_check_citations`.
- Abstain-on-failure semantics: any parse/timeout error must still → abstain.
- Never instruct it to exceed menu candidates, ignore gates, or assume fills.

## Procedure
1. Quote, in your review, the exact journal reasoning lines that motivated the
   change (cycle_ids), per `analyze-regret` steps 3–4.
2. Edit SYSTEM_PROMPT in `llm_reasoner.py`; keep the schema section verbatim.
3. If you add/rename facts: update where they're built (`bot.py` find_candidates /
   `spread_builder.py`) AND the citation test in `tests/`.
4. Run `python -m pytest tests/ -q`; the wrapper's forced dry cycle will
   exercise the new prompt end-to-end.
5. NIGHTLY.md entry must contain a falsifiable prediction: which metric
   (regret count, agreement rate, abstention rate) should move which way
   tomorrow. Next session: verdict it.
