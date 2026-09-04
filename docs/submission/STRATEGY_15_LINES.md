# The strategy in 15 lines (submission text)

1. We sell defined-risk options spreads (credit verticals) on liquid US index ETFs — collecting premium that decays as time passes, with the maximum possible loss fixed mathematically at entry.
2. An algorithmic funnel does everything deterministic: screening, momentum signals, trend and volatility filters, strike selection, sizing, and a hard risk gate.
3. The AI (Claude Opus 4.8) is deliberately given only one power: choose among pre-approved candidates — or refuse to trade. It cannot invent trades, resize them, or bypass a gate.
4. Every number the AI reasons with is a cited fact with provenance (`[QQQ_CREDIT_EST]`, source, timestamp, quality); its full reasoning is journaled verbatim and browsable on our public audit page.
5. A second deterministic gate re-verifies everything against fresh quotes after the AI chooses; abstention is the default outcome, not a failure.
6. Exits are mechanical — 50% profit target, 2× credit stop, forced close near expiry — and macro blackout windows block entries around JOLTS/NFP releases.
7. Every cycle, two counterfactual books trade the identical menu: a mechanical rule and a random policy — a live ablation measuring, in dollars, whether the AI's judgment adds value.
8. A "menu book" tracks every candidate nobody picked, so we can measure the AI's regret, not just its wins.
9. Each night, a second AI (Claude Fable 5) reads the day's full evidence and may rewrite the trading algorithm — its changes survive only if compilation, the 85-test suite, and a forced simulation cycle all pass; otherwise everything reverts automatically.
10. That nightly engineer found and fixed real structural bugs four nights in a row (a vestigial price cap silently excluding SPY, a trend filter computing ADX but never using it, a judge blind to its own book, a builder emitting impossible ITM "credit spreads").
11. Its changes ship with falsifiable predictions ("duplicate opens drop from 6/day to ≤2") that the next session must verify — the scientific method as an agent loop, with every verdict public.
12. Strategy parameters were chosen by measurement, not taste: a 16-month component-ladder backtest (raw signals −$1,967 → +trend −$1,069 → +vol filter +$1,289) with honest proxy-pricing caveats printed on every run.
13. The live ablation result: across an adverse, whipsawing week, the AI's book lost measurably less than the mechanical rule (−$620 vs −$1,101) on identical information — it refused the broken trades and the noise signals its baseline swallowed.
14. We claim no statistically proven alpha in four days — we claim something rarer: an autonomous trading agent whose every decision, mistake, self-repair and refusal is auditable, gated, and measured against its own counterfactuals.
15. Everything runs unattended in production — cron + Alpaca MCP for all data and orders, Supabase Postgres as the single source of truth, a Next.js dashboard on Vercel, and the same dashboard as a Telegram Mini App — the whole week's decision history one tap away, even from a phone.
