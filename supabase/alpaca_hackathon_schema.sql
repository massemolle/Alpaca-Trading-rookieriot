-- alpaca_hackathon schema — RECONSTRUCTED 2026-08-28 from db.py's queries and
-- the live /api/state payload (the original file referenced by db.py's
-- docstring was never pushed). Alex: diff this against your local version.
--
-- decision_journal is ALSO auto-created by db.py (_ensure_decision_journal_table);
-- included here for completeness with the identical definition.
-- The call_* / strategy columns on spreads are nullable forward-compat columns
-- observed in the live deployment's iron-condor rows (not yet written by the
-- pushed db.py).

CREATE SCHEMA IF NOT EXISTS alpaca_hackathon;

CREATE TABLE IF NOT EXISTS alpaca_hackathon.cycles (
    id          SERIAL PRIMARY KEY,
    candidates  JSONB,
    decision    TEXT,
    reasoning   TEXT,
    error       TEXT,
    ran_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.spreads (
    id                SERIAL PRIMARY KEY,
    underlying        TEXT NOT NULL,
    direction         TEXT NOT NULL,
    expiration        DATE,
    short_strike      NUMERIC,
    long_strike       NUMERIC,
    short_symbol      TEXT,
    long_symbol       TEXT,
    contracts         INTEGER,
    credit_received   NUMERIC,
    max_loss          NUMERIC,
    alpaca_order_ids  JSONB,
    cycle_id          INTEGER REFERENCES alpaca_hackathon.cycles(id),
    status            TEXT NOT NULL DEFAULT 'open',
    realized_pnl      NUMERIC,
    opened_at         TIMESTAMPTZ DEFAULT now(),
    closed_at         TIMESTAMPTZ,
    est_credit        NUMERIC,  -- original estimate preserved for slippage reporting
    -- forward-compat (iron condor support seen in the live deployment)
    strategy          TEXT,
    call_short_strike NUMERIC,
    call_long_strike  NUMERIC,
    call_short_symbol TEXT,
    call_long_symbol  TEXT
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.account_snapshots (
    id                  SERIAL PRIMARY KEY,
    equity              NUMERIC NOT NULL,
    last_equity         NUMERIC,
    cash                NUMERIC,
    open_spreads_count  INTEGER,
    daily_pl            NUMERIC,
    daily_pl_pct        NUMERIC,
    spy_price           NUMERIC,
    snapshot_at         TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.decision_journal (
    id                   SERIAL PRIMARY KEY,
    cycle_id             INTEGER REFERENCES alpaca_hackathon.cycles(id),
    candidates           JSONB,
    llm_selected         JSONB,
    llm_reasoning        TEXT,
    shadow_selected      JSONB,
    gate_rejections      JSONB,
    pre_trade_rejections JSONB,
    created_at           TIMESTAMPTZ DEFAULT now()
);

-- Live-ablation shadow book (PR4): virtual positions for the mechanical
-- 'shadow' rule and a matched-rate 'random' policy, on the same
-- gate-approved candidates the LLM chose from. Also holds the 'menu'
-- policy: EVERY gate-approved candidate tracked for regret analysis —
-- not risk-matched, so ablation queries must filter it out.
CREATE TABLE IF NOT EXISTS alpaca_hackathon.shadow_positions (
    id               SERIAL PRIMARY KEY,
    cycle_id         INTEGER REFERENCES alpaca_hackathon.cycles(id),
    policy           TEXT NOT NULL,
    underlying       TEXT NOT NULL,
    direction        TEXT NOT NULL,
    expiration       DATE,
    short_strike     NUMERIC,
    long_strike      NUMERIC,
    short_symbol     TEXT,
    long_symbol      TEXT,
    contracts        INTEGER,
    credit_received  NUMERIC,
    max_loss         NUMERIC,
    status           TEXT NOT NULL DEFAULT 'open',
    unrealized_mark  NUMERIC,
    realized_pnl     NUMERIC,
    same_as_llm      BOOLEAN DEFAULT FALSE,
    opened_at        TIMESTAMPTZ DEFAULT now(),
    closed_at        TIMESTAMPTZ
);

-- Fill / pending tracking (weekend hardening)
ALTER TABLE alpaca_hackathon.spreads
    ADD COLUMN IF NOT EXISTS fill_credit NUMERIC,
    ADD COLUMN IF NOT EXISTS client_order_id TEXT;

-- Offline lab results (append-only; run_id scopes each experiment)
CREATE TABLE IF NOT EXISTS alpaca_hackathon.lab_summary (
    id            SERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL,
    config        TEXT NOT NULL,
    n_trades      INTEGER,
    total_pnl     NUMERIC,
    win_rate      NUMERIC,
    avg_pnl       NUMERIC,
    max_drawdown  NUMERIC,
    run_at        TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alpaca_hackathon.lab_trades (
    id            SERIAL PRIMARY KEY,
    run_id        TEXT NOT NULL,
    config        TEXT NOT NULL,
    symbol        TEXT,
    direction     TEXT,
    entry_date    DATE,
    exit_date     DATE,
    credit        NUMERIC,
    pnl           NUMERIC,
    exit_reason   TEXT
);

-- Nightly engineer audit trail (D19/D20): one row per evening session.
CREATE TABLE IF NOT EXISTS alpaca_hackathon.nightly_sessions (
    id           SERIAL PRIMARY KEY,
    session_date DATE,
    verdict      TEXT,      -- KEPT | REVERTED | NO-CHANGE
    summary      TEXT,      -- engineer's own review (tail)
    gate_tail    TEXT,      -- gate log tail (failures when REVERTED)
    created_at   TIMESTAMPTZ DEFAULT now()
);
