# premium_buyer — long-premium sleeve (parallel to the credit bot)

A second, independent options strategy running on the SAME account as the
credit-spread bot, built after reviewing the hackathon winners' code. Where
the main bot SELLS premium (profits from calm), this BUYS it (profits from
moves) — directly inspired by the champion "Autobelay" (MIT-licensed;
mechanics re-implemented, not copied wholesale).

**Why parallel, not merged:** different edge, different regime, different
risk shape. Kept in its own folder, own book, own cron, own caps so neither
strategy can disturb the other. The credit bot's reconciler is taught to
ignore this sleeve's legs (`reconciler._exclude_foreign_legs`).

## What it does
Buy ~0.40Δ calls/puts, 5–14 DTE, on a directional swing signal, only when
the option is **fairly priced** (mid ≤ 1.40× its Black-Scholes value at
realized vol — the Killswitch richness gate, inverted for a buyer). Leash:
−40% stop / +60% take / expiry-day close, $500/position, 4 positions, daily
loss halt, entries only 13:45–19:15 UTC. The LLM proposes with cited facts
and a required `p_move`; code disposes; abstention is default.

## Two capabilities the credit bot didn't have
- **Rhetoric audit** (`rhetoric.py`): verifies the VALUES the model quotes
  match the facts it was given, and that a pick doesn't contradict its own
  stated probability. Violations → the cycle abstains and journals the flags.
- **Brier scoring** (`brier.py`): every stated probability — taken AND
  declined — is recorded and later scored against what the underlying did.
  Converges in days; tells us whether the judge actually knows anything.

## Run
`./run_premium_cron.sh` (cron :15/:45, offset from the credit bot).
`DRY_RUN=true` until a live rehearsal passes. Tables auto-create in the
shared Supabase schema (`premium_positions`, `premium_journal`,
`premium_predictions`). Keep `DRY_RUN=true` to paper-rehearse.
