// Lab data: the incremental backtest's summary ladder + full per-trade
// history — the inspectable evidence behind the aggregate claims.
import { NextResponse } from 'next/server';
import { getLabState } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    return NextResponse.json(await getLabState());
  } catch (err) {
    console.error('Failed to load lab state', err);
    return NextResponse.json({ error: 'Failed to load lab state' }, { status: 500 });
  }
}
