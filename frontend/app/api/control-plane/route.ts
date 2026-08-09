import { NextResponse } from "next/server";
import type { BaselineSnapshot, ControlPlaneSnapshot } from "@/lib/control-plane-types";
import {
  backendResponse,
  controlPlaneFetch,
  hasRemoteControlPlane,
} from "@/lib/control-plane-backend";
import { hasControlPlaneConfig, loadCommittedBaseline, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const EMPTY_BASELINE: BaselineSnapshot = {
  hardware: { gpu: "unavailable", vramGb: 0, contextTokens: 0 },
  latency: [],
  throughput: [],
  accuracy: [],
};

export async function GET() {
  if (hasRemoteControlPlane()) {
    try {
      return backendResponse(await controlPlaneFetch("/v1/control-plane"));
    } catch {
      return NextResponse.json(
        {
          connected: false,
          mode: "baseline",
          reason: "The remote control plane is unavailable",
          baseline: EMPTY_BASELINE,
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
  }

  // Baseline data is decorative; its absence (missing results/, private research
  // repo, no GITHUB_TOKEN) must never report the live control plane as down.
  const baseline = await loadCommittedBaseline().catch(() => EMPTY_BASELINE);
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
