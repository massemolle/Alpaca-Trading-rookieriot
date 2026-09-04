# Video outline (~3 min, screen-recorded, voiceover)

Tone: calm, evidence-first. No hype words. Every claim shown on screen as it's said.
Record AFTER Friday flatten (~13:30 Paris) so numbers are final.

## Scene 1 — Hook (0:00–0:15)
Screen: /audit page scrolling slowly through cited reasoning.
VO: "Every AI trading agent claims it's smart. Ours has to prove it —
every 30 minutes, in writing, with citations. This is team rookieriot."

## Scene 2 — The problem (0:15–0:40)
Screen: simple slide, three failure words: Overtrades. Hallucinates. Unverifiable.
VO: "The research on LLM traders is brutal: they overtrade, they invent
numbers, and you can't audit why. So we didn't build a smarter trader —
we built a constrained one."

## Scene 3 — Architecture in one breath (0:40–1:10)
Screen: pipeline diagram (README mermaid): screen → signals → filters →
gate → AI chooses/abstains → gate → limit order.
VO: "Code generates candidates and enforces risk — twice. The AI holds one
power only: pick from the pre-approved menu, or refuse. Refusal is the
default. Every number it reasons with is a cited, timestamped fact.
Defined-risk spreads only: worst case fixed at entry."

## Scene 4 — The ablation (1:10–1:40)  ← the core claim
Screen: dashboard ablation panel, then /audit XLK refusal.
VO: "Here's the experiment nobody runs: every cycle, a mechanical rule and
a random policy trade the same menu as the AI. Same information, same
execution. In a whipsawing losing week, the AI lost $480 less than its
mechanical baseline — because it refused the broken trades and the noise.
[FINAL NUMBER — update after flatten] Judgment, measured in dollars."

## Scene 5 — The machine that fixes itself (1:40–2:30)
Screen: /audit nightly trail: REVERTED entry first, then the KEPT streak.
VO: "Every night, a second AI reads the day's evidence and may rewrite the
algorithm — inside a hard gate: 85 tests and a forced simulation, or
everything reverts. Night one, the gate threw its work away. Then it found
a price cap silently excluding SPY itself... a trend filter ignoring its
own trend-strength math... a judge blind to its own positions. Each fix
shipped with a prediction — and the next night verified it. Four nights,
four repairs, all public, failures included."

## Scene 6 — Honesty + close (2:30–3:00)
Screen: /lab ladder table, then equity curve with SPY overlay.
VO: "Every parameter earned its place in a 16-month measured ladder — with
its caveats printed on the page. Four days of P&L is noise, and our
dashboard says so next to our own benchmark. What we built is the part
that isn't noise: a fully auditable, self-repairing, counterfactual-
measured trading agent. Team rookieriot — ask it why. It has receipts."

## Shot checklist
- [ ] Dashboard home (equity + SPY + ablation) — AFTER final flatten
- [ ] /audit: cycle 53 expanded (AI vs rule divergence)
- [ ] /audit: XLK refusal + a [QQQ_OPEN_SPREADS] abstention
- [ ] /audit: nightly trail incl. the REVERTED entry
- [ ] /lab ladder
- [ ] README architecture diagram
