import { NextResponse } from "next/server";
import {
  backendResponse,
  controlPlaneFetch,
  hasRemoteControlPlane,
} from "@/lib/control-plane-backend";
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
  if (hasRemoteControlPlane()) {
    try {
      return backendResponse(await controlPlaneFetch(
        `/v1/agents/${encodeURIComponent(sandbox)}/repair`,
        { method: "POST" },
        900_000,
      ));
    } catch {
      return NextResponse.json({ error: "The remote control plane is unavailable" }, { status: 502 });
    }
  }
  if (!hasControlPlaneConfig()) {
    return NextResponse.json({ error: "Control plane is not configured" }, { status: 503 });
  }
  try {
    const stdout = await runGtz(["repair-chat", sandbox], 900_000);
    const result = JSON.parse(stdout.trim().split("\n").at(-1) ?? "{}") as {
      repaired: boolean;
      session_id: string;
      reinitialized?: boolean;
    };
    return NextResponse.json(result);
  } catch {
    return NextResponse.json({ error: "Agent repair failed" }, { status: 502 });
  }
}
