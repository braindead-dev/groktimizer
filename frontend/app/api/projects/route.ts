import { spawn } from "node:child_process";
import { NextResponse } from "next/server";
import type { ControlPlaneSnapshot } from "@/lib/control-plane-types";
import { controlPlaneRoot, hasControlPlaneConfig, runGtz, uvExecutable } from "@/lib/control-plane-server";

export const runtime = "nodejs";

export async function POST(request: Request) {
  if (!hasControlPlaneConfig()) {
    return NextResponse.json({ error: "Control plane is not configured" }, { status: 503 });
  }
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const objective = typeof body === "object" && body !== null && "objective" in body
    ? (body as { objective?: unknown }).objective
    : null;
  if (typeof objective !== "string" || !objective.trim() || objective.length > 8_000) {
    return NextResponse.json({ error: "Objective must contain 1–8,000 characters" }, { status: 400 });
  }

  try {
    const snapshot = JSON.parse(await runGtz(["snapshot"])) as ControlPlaneSnapshot;
    const existing = snapshot.agents.find((agent) => agent.role === "main");
    if (existing) {
      return NextResponse.json(
        { error: `The main orchestrator already exists at ${existing.sandbox_name}` },
        { status: 409 },
      );
    }

    const child = spawn(uvExecutable(), ["run", "gtz", "start", objective.trim()], {
      cwd: controlPlaneRoot(),
      env: process.env,
      detached: true,
      stdio: "ignore",
    });
    child.on("error", () => undefined);
    child.unref();
    return NextResponse.json(
      { started: true, sandbox: `gtz-${snapshot.project}-hq-main`, state: "provisioning" },
      { status: 202 },
    );
  } catch {
    return NextResponse.json({ error: "Project launch failed" }, { status: 502 });
  }
}
