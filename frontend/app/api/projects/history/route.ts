import { NextResponse } from "next/server";
import { readProjectHistory } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  return NextResponse.json(readProjectHistory(), {
    headers: { "Cache-Control": "no-store" },
  });
}
