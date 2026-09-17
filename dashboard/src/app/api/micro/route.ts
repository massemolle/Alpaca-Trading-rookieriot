import { NextResponse } from 'next/server';
import { getMicroState } from '@/lib/db';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    return NextResponse.json(await getMicroState());
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 });
  }
}
