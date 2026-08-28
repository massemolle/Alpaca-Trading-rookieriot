// RECONSTRUCTED 2026-08-28 — this Route Handler existed only in the original
// deployment and was never pushed; rebuilt around src/lib/db.ts's
// getDashboardState(), whose return shape matches the live /api/state payload.
// Alex: diff against your local version.
import { NextResponse } from 'next/server';
import { getDashboardState } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const state = await getDashboardState();
    return NextResponse.json(state);
  } catch (err) {
    console.error('Failed to load dashboard state', err);
    const detail = err instanceof Error ? err.message : String(err);
    return NextResponse.json({ error: 'Failed to load agent state', detail }, { status: 500 });
  }
}
