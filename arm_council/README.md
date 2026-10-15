# arm_council — "Should-AI Buy?" replication (2nd place)

Re-implementation of the hackathon's 2nd-place system
(github.com/nabielnovelkhubran/Should-AI-Buy, **Business Source License
1.1** — full text in `LICENSE-SHOULD-AI-BUY.txt`; its Additional Use Grant
permits non-commercial research/testing use including paper trading, which
is this project's only use). Their stack is a Next.js app; this is a Python
re-implementation from a line-level spec of their TypeScript.

## Two things to know about the original
1. **It trades long US equities, not options.** Its option-contract selector
   exists but never reaches order submission — dead code. This arm trades
   equities too, faithfully.
2. **Its 7-stage "AI council" is 100% deterministic.** No LLM decides
   anything; the one optional model call can only DOWNGRADE a BUY. Kept
   exactly so — which makes this our **control arm**: same execution and
   journaling as the others, zero model judgment.

## Pipeline
snapshot → liquidity/spread screen → multi-factor score (8 weighted
factors) + R:R floor → rank → **council**: discovery → quant ∥ intelligence
∥ risk → red team (4 attacks; ≥2 vulnerabilities = DISPROVED = veto) →
decision (strict precedence, no voting) → risk gate (6 checks) → sizing
(volatility penalty × conviction, floored) → market buy. Exits run first and
ungated: drawdown, momentum reversal, profit target with exhaustion,
liquidity collapse, risk-score breach.

## Longer-term twist (operator, 2026-10-15)
Exits widened for a longer horizon: drawdown −5% → **−8%**, profit target
+4/5% → **+10%**, momentum-reversal floor 40 → **30**. Everything else is
their STANDARD profile verbatim.
