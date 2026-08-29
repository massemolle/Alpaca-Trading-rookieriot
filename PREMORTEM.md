# Pre-mortem — "It's Sep 4 and we failed. What happened?"

Each imagined failure must map to a guard (code) or a test. Update as guards land.
Status: ☐ open ☑ guarded

| # | Imagined failure | Guard / test | Status |
|---|---|---|---|
| 1 | Agent traded on a phantom position it had already closed | `reconciler.reconcile` every cycle blocks entries on mismatch; chaos/hardening tests | ☑ |
| 2 | Multi-leg orders never worked through our MCP client; found out Tuesday | Spike + smoke_test; limit mleg path in `executor_mcp.py` | ☐ (validate live Monday) |
| 3 | A timed-out submit was blindly retried → double position | Idempotent `client_order_id`; poll order state; pending DB rows | ☑ |
| 4 | Stale / missing-timestamp quotes priced candidates | Quote-age + missing timestamp fail-closed in `pretrade_gate.py` | ☑ |
| 5 | Short leg assigned early over a weekend/ex-dividend | ETF-only universe reduces risk; single names disabled; no full assignment poll yet | ☐ (mitigated, not closed) |
| 6 | Position still open / undemonstrated at deadline | Force-close flag + RTH-only verified limit close in `bot.manage_open_spreads` | ☑ |
| 7 | Prompt injection in a news article steered the selector | Structural menu isolation; news never touches risk config | ☐ |
| 8 | LLM "improved" the strategy nightly and overfit to 3 trades | Frozen params; no reflector/extra LLM; mechanical score centralized | ☑ |
| 9 | Token spend blew up; pipeline silently stopped mid-week | Cron non-zero exit; abstain-on-reasoner-failure | ☐ (partial) |
| 10 | Greeks said safe; overnight gap blew through approximation | Defined-risk verticals + stop; quantity-aware max loss | ☐ (partial) |
| 11 | Dashboard showed demo data, not real decisions | Dashboard reads persisted cycles / journal / spreads | ☑ |
| 12 | Fresh-account rule misread; submission invalid | Dedicated account + smoke_test equity check | ☐ (ops) |
| 13 | One malformed API response crashed the scheduler for hours | Chaos tests; flock; fail-closed market clock | ☑ |
| 14 | Collar / non-atomic legs left half-open | Prefer mleg; reconciler flags unexplained option symbols | ☐ (partial) |
| 15 | Sizing after gate → oversized risk | `optimal_contracts` before gates; multi-contract pretrade tests | ☑ |
| 16 | Mark-to-market wrong by 100× → false stops/targets | `spread_monitor` / marks use ×100; regression test | ☑ |
| 17 | Cron reported success while bot failed | `run_options_cron.sh` exits with bot status | ☑ |
| 18 | Experiment incomparable (LLM vs shadow different menus/budgets) | Shared menu + aggregate max-loss match + shared `mechanical_score` | ☑ |

## Explicit unresolved risks (do not paper over)

- Early assignment / pin risk on American options near expiry.
- Ex-dividend / earnings on single names (why ETF core is frozen).
- Indicative feed slippage vs true OPRA; paper ≠ live market impact.
- One-week sample cannot establish LLM alpha.
