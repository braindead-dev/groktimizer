import { NextResponse } from "next/server";
import { hasControlPlaneConfig, isSandboxName, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";

export async function DELETE(_request: Request, context: { params: Promise<{ sandbox: string }> }) {
  const { sandbox } = await context.params;
  if (!isSandboxName(sandbox)) {
    return NextResponse.json({ error: "Invalid sandbox" }, { status: 400 });
  }
  if (!hasControlPlaneConfig()) {
    return NextResponse.json({ error: "Control plane is not configured" }, { status: 503 });
  }
  try {
    await runGtz(["kill", sandbox], 60_000);
    return NextResponse.json({ deleted: true, sandbox });
  } catch {
    return NextResponse.json({ error: "Agent teardown failed" }, { status: 502 });
  }
}
