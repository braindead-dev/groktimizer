import { NextResponse } from "next/server";
import { isSandboxName } from "@/lib/control-plane-server";
import { readAgentHistory } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ sandbox: string }> }) {
  const { sandbox } = await context.params;
  if (!isSandboxName(sandbox)) {
    return NextResponse.json({ error: "Invalid sandbox" }, { status: 400 });
  }
  return NextResponse.json(readAgentHistory(sandbox), {
    headers: { "Cache-Control": "no-store" },
  });
}
