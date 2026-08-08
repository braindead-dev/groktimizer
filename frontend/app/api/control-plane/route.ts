import { NextResponse } from "next/server";
import type { ControlPlaneSnapshot } from "@/lib/control-plane-types";
import { hasControlPlaneConfig, loadCommittedBaseline, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  const baseline = await loadCommittedBaseline();
  if (!hasControlPlaneConfig()) {
    return NextResponse.json(
      { connected: false, mode: "baseline", reason: "No groktimizer.toml is configured", baseline },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const output = await runGtz(["snapshot"]);
    const snapshot = JSON.parse(output) as ControlPlaneSnapshot;
    return NextResponse.json(
      { connected: true, snapshot, baseline },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { connected: false, mode: "baseline", reason: "The local control plane is unavailable", baseline },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
}
