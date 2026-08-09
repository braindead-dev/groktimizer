import { NextResponse } from "next/server";
import {
  backendResponse,
  controlPlaneFetch,
  hasRemoteControlPlane,
} from "@/lib/control-plane-backend";
import { readProjectHistory } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  if (hasRemoteControlPlane()) {
    try {
      return backendResponse(await controlPlaneFetch("/v1/projects/history"));
    } catch {
      return NextResponse.json({ projects: [], agents: [] }, { status: 502 });
    }
  }
  return NextResponse.json(readProjectHistory(), {
    headers: { "Cache-Control": "no-store" },
  });
}
