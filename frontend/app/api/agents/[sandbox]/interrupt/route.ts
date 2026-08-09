import { NextResponse } from "next/server";
import { hasControlPlaneConfig, isSandboxName, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";

export async function POST(
  _request: Request,
  context: { params: Promise<{ sandbox: string }> },
) {
  const { sandbox } = await context.params;
  if (!isSandboxName(sandbox)) {
    return NextResponse.json({ error: "Invalid sandbox" }, { status: 400 });
  }
  if (!hasControlPlaneConfig()) {
    return NextResponse.json({ error: "Control plane is not configured" }, { status: 503 });
  }

  try {
    const stdout = await runGtz(["interrupt-chat", sandbox], 30_000);
    const result = JSON.parse(stdout.trim().split("\n").at(-1) ?? "{}") as {
      interrupted: boolean;
      turn_id: string | null;
    };
    return NextResponse.json(result);
  } catch {
    return NextResponse.json({ error: "The active response could not be stopped" }, { status: 502 });
  }
}
