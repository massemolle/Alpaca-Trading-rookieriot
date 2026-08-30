import { NextResponse } from 'next/server';
import { getAuditState } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    return NextResponse.json(await getAuditState());
  } catch (err) {
    console.error('Failed to load audit state', err);
    return NextResponse.json({ error: 'Failed to load audit state' }, { status: 500 });
  }
}
