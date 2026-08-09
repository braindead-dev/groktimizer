import { NextResponse } from "next/server";
import type { ControlPlaneSnapshot } from "@/lib/control-plane-types";
import {
  backendResponse,
  controlPlaneFetch,
  hasRemoteControlPlane,
} from "@/lib/control-plane-backend";
import { hasControlPlaneConfig, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  if (hasRemoteControlPlane()) {
    try {
      return backendResponse(await controlPlaneFetch("/v1/control-plane"));
    } catch {
      return NextResponse.json(
        {
          connected: false,
          mode: "offline",
          reason: "The remote control plane is unavailable",
        },
        { headers: { "Cache-Control": "no-store" } },
      );
    }
  }

  if (!hasControlPlaneConfig()) {
    return NextResponse.json(
      { connected: false, mode: "offline", reason: "No groktimizer.toml is configured" },
      { headers: { "Cache-Control": "no-store" } },
    );
  }

  try {
    const output = await runGtz(["snapshot"]);
    const snapshot = JSON.parse(output) as ControlPlaneSnapshot;
    return NextResponse.json(
      { connected: true, snapshot },
      { headers: { "Cache-Control": "no-store" } },
    );
  } catch {
    return NextResponse.json(
      { connected: false, mode: "offline", reason: "The local control plane is unavailable" },
      { headers: { "Cache-Control": "no-store" } },
    );
  }
}
