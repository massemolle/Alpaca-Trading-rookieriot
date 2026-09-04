# Demo script — live dashboard walkthrough (~4 minutes)

Presenter: Guillaume. Everything shown is live production data, not mockups.
URL: https://alpaca-trading-rookieriot.vercel.app
[FINAL NUMBERS: refresh equity / ablation totals ~13:30 Paris Friday before recording.]

## 0. Framing (20s)
"Most AI trading demos show you a chatbot that claims it trades well.
We built the opposite: an agent that has to prove every decision — so let me
show you not the AI, but its receipts."

## 1. Home dashboard (45s)
- Point: equity curve with the SPY overlay (dashed) — "our benchmark is drawn
  on our own chart; we don't hide a losing comparison."
- Point: **Ablation panel** — three P&L figures side by side.
  "Every 30 minutes, three deciders faced the exact same pre-approved menu:
  our AI, a mechanical rule, and a coin flip. Identical information,
  identical execution. This is the experiment most trading bots never run —
  is the AI actually the reason for the result? This week's answer: the AI
  lost $480 LESS than its own mechanical baseline, mostly by refusing trades."
- Point: per-trade slippage line — "estimated vs filled, printed on every
  trade. Real fills, not simulator gifts."

## 2. /audit — the heart (90s)
- Open a trade cycle (e.g., Sep 2, cycle 53 — first menu):
  "Three candidates. The AI picked QQQ; the mechanical rule picked XLK.
  Here is the AI's complete reasoning, verbatim — and notice every number
  carries a citation: [QQQ_SIGNAL_STRENGTH], [QQQ_CREDIT_EST]. Each cites a
  fact with source and timestamp. The model is not allowed to use a number
  it can't cite."
- Open the XLK refusal:
  "The rule bought this XLK spread. The AI refused it — its 'credit' was
  larger than its max loss, a data artifact. The rule's copy is marked
  −$203 in the shadow book. That refusal is the value of judgment, in dollars."
- Open a Sep 3 abstention:
  "Seven straight refusals, each citing [QQQ_OPEN_SPREADS] — the AI knows
  what its book already holds and declines to stack the same bet. That
  capability is three days old, and it was built by... this:"

## 3. /audit — Nightly Engineer trail (60s)
- Scroll to the nightly sessions:
  "Every evening a second AI reads the day's evidence and may rewrite the
  trading algorithm. Its changes survive ONLY if the full test suite and a
  forced simulation cycle pass — here's a night where the gate REVERTED it,
  failures included. Nothing is curated away."
- Point at Sep 1–3 KEPT entries:
  "Four nights, four real discoveries: a leftover price cap that silently
  excluded SPY itself; a trend filter that computed trend strength and then
  ignored it; a judge that couldn't see its own positions; a builder
  emitting impossible spreads. Each fix shipped with a falsifiable
  prediction — 'duplicates drop to ≤2 tomorrow' — and the NEXT night's
  session verified it and cancelled its own escalation plan. The scientific
  method, running as a cron job."

## 4. /lab (30s)
- "Nothing here was chosen by taste. The component ladder: raw signals lose
  $1,967 over 16 months; add the trend filter, lose $1,069; add the vol
  filter, MAKE $1,289. Every filter earned its place by measurement — and
  the caveats (proxy pricing, relative comparisons only) are printed in the
  header, not a footnote."

## 5. Close (20s)
"Four days of P&L is noise, and we say so on the page. What we're
submitting is the thing that survives contact with noise: an agent whose
every trade, refusal, bug, and self-repair is public, gated, and measured
against its own counterfactuals. Ask it why it did anything — it will show
you the receipt."
