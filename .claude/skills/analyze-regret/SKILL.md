---
name: analyze-regret
description: Nightly evidence review — decide whether today's weak spot was the pipeline (candidates/signals) or the judge (LLM selector), using the ablation books and the menu_regret table. Use before proposing any change.
---

# Analyze regret & ablation

Goal: locate today's weakest link with evidence, not vibes.

1. Load `state/evening_context.json`.
2. **Ablation first** (`shadow_positions` summary): compare realized+unrealized
   P&L of the LLM book (real `spreads`) vs 'shadow' (rule) vs 'random'.
   - LLM ≥ rule ≥ random → system healthy; look elsewhere for improvements.
   - rule > LLM consistently → the judge is the weak link → `tune-reasoner-prompt`.
   - random ≈ rule → signals carry no information → look at `signals/` thresholds.
3. **Regret** (`menu_regret`): for each dropped-but-profitable candidate,
   pull the journal entry for that `cycle_id` and read the LLM's cited
   reasoning verbatim. Classify each miss:
   - (a) reasoning was sound, outcome lucky → NOT evidence; note and move on.
   - (b) a fact was misread/overweighted (name it, e.g. REALIZED_VOL) → prompt fix.
   - (c) candidate quality was misrepresented by our facts → pipeline fix.
4. A pattern = the SAME class (b) or (c) across ≥3 decisions or ≥2 days.
   One miss is noise — say so explicitly and stop.
5. Output in your review: the classification table, the single strongest
   pattern (or "no pattern"), and which module owns the fix.

Caveats: outcomes of open menu rows are marks, not fills; menu book is not
risk-matched — never compare its total against the policy books.
