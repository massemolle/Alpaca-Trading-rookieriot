// Server-only — direct Postgres against the same Supabase project Agent
// Bazaar uses, isolated in its own `alpaca_hackathon` schema (see
// db.py for why this goes through Postgres directly
// rather than PostgREST: that schema isn't in the project's "exposed
// schemas" list, and this avoids needing that dashboard setting changed).
//
// This file must never be imported from a Client Component — the DB
// credentials live in server-only env vars, read only inside the
// `/api/state` Route Handler.
import { Pool } from 'pg';

let pool: Pool | null = null;

function getPool(): Pool {
  if (!pool) {
    pool = new Pool({
      host: process.env.SUPABASE_DB_HOST,
      port: Number(process.env.SUPABASE_DB_PORT || 5432),
      database: process.env.SUPABASE_DB_NAME || 'postgres',
      user: process.env.SUPABASE_DB_USER,
      password: process.env.SUPABASE_DB_PASSWORD,
      ssl: { rejectUnauthorized: false },
      max: 3,
    });
  }
  return pool;
}

const SCHEMA = process.env.SUPABASE_SCHEMA || 'alpaca_hackathon';

export interface AccountSnapshot {
  equity: number;
  last_equity: number | null;
  cash: number | null;
  open_spreads_count: number;
  daily_pl: number | null;
  daily_pl_pct: number | null;
  spy_price: number | null;
  snapshot_at: string;
}

export interface Spread {
  id: number;
  underlying: string;
  direction: string;
  expiration: string;
  short_strike: number;
  long_strike: number;
  contracts: number;
  credit_received: number;
  max_loss: number;
  status: string;
  realized_pnl: number | null;
  opened_at: string;
  closed_at: string | null;
}

export interface Cycle {
  id: number;
  ran_at: string;
  decision: string | null;
  reasoning: string | null;
  error: string | null;
}

export async function getDashboardState() {
  const client = await getPool().connect();
  try {
    const [snapshot, spreads, cycles] = await Promise.all([
      client.query<AccountSnapshot>(
        `select equity, last_equity, cash, open_spreads_count, daily_pl, daily_pl_pct, spy_price, snapshot_at
         from ${SCHEMA}.account_snapshots order by snapshot_at desc limit 1`
      ),
      client.query<Spread>(
        `select id, underlying, direction, expiration, short_strike, long_strike,
                contracts, credit_received, max_loss, status, realized_pnl, opened_at, closed_at
         from ${SCHEMA}.spreads order by opened_at desc limit 50`
      ),
      client.query<Cycle>(
        `select id, ran_at, decision, reasoning, error
         from ${SCHEMA}.cycles order by ran_at desc limit 20`
      ),
      // Equity curve for the chart — every snapshot, not just the latest.
    ]);
    const curve = await client.query<Pick<AccountSnapshot, 'equity' | 'snapshot_at' | 'spy_price'>>(
      `select equity, spy_price, snapshot_at from ${SCHEMA}.account_snapshots order by snapshot_at asc`
    );

    // Live ablation: cumulative P&L per selection policy. The real book
    // ('llm') comes from spreads; counterfactuals from shadow_positions.
    // For open positions, unrealized = (credit - mark) x contracts; real
    // book marks aren't stored per-spread, so its open P&L is reflected in
    // account equity instead — we report realized + open counts per policy.
    const shadow = await client.query(
      `select policy,
              coalesce(sum(realized_pnl) filter (where status <> 'open'), 0) as realized,
              coalesce(sum((credit_received - unrealized_mark) * contracts)
                       filter (where status = 'open' and unrealized_mark is not null), 0) as unrealized,
              count(*) filter (where status = 'open') as open_count,
              count(*) filter (where status <> 'open') as closed_count
       from ${SCHEMA}.shadow_positions group by policy`
    );
    const llmBook = await client.query(
      `select coalesce(sum(realized_pnl) filter (where status <> 'open'), 0) as realized,
              count(*) filter (where status = 'open') as open_count,
              count(*) filter (where status <> 'open') as closed_count
       from ${SCHEMA}.spreads`
    );

    return {
      latestSnapshot: snapshot.rows[0] ?? null,
      spreads: spreads.rows,
      cycles: cycles.rows,
      equityCurve: curve.rows,
      ablation: {
        llm: llmBook.rows[0] ?? null,
        policies: shadow.rows,
      },
    };
  } finally {
    client.release();
  }
}
