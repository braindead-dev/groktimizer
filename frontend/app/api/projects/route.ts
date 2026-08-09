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
  const project = typeof body === "object" && body !== null && "project" in body
    ? (body as { project?: unknown }).project
    : null;
  if (typeof objective !== "string" || !objective.trim() || objective.length > 8_000) {
    return NextResponse.json({ error: "Objective must contain 1–8,000 characters" }, { status: 400 });
  }
  if (typeof project !== "string" || !/^[a-z0-9]{1,24}$/.test(project)) {
    return NextResponse.json({ error: "Project id must contain 1–24 lowercase letters or numbers" }, { status: 400 });
  }

  try {
    const snapshot = JSON.parse(await runGtz(["snapshot"])) as ControlPlaneSnapshot;
    const projectSnapshot = snapshot.projects.find((candidate) => candidate.project === project);
    const existing = projectSnapshot?.agents.find((agent) => agent.role === "main");
    if (existing) {
      return NextResponse.json(
        { started: true, project, sandbox: existing.sandbox_name, state: "running", existing: true },
        { status: 200 },
      );
    }
    if (projectSnapshot?.project_state.status === "provisioning") {
      return NextResponse.json(
        {
          started: true,
          project,
          sandbox: `gtz-${project}-hq-main`,
          state: "provisioning",
        },
        { status: 202 },
      );
    }

    const child = spawn(
      uvExecutable(),
      ["run", "gtz", "start", objective.trim(), "--project", project],
      {
      cwd: controlPlaneRoot(),
      env: process.env,
      detached: true,
      stdio: "ignore",
      },
    );
    await new Promise<void>((resolve, reject) => {
      child.once("spawn", resolve);
      child.once("error", reject);
    });
    child.unref();
    return NextResponse.json(
      {
        started: true,
        project,
        sandbox: `gtz-${project}-hq-main`,
        state: "provisioning",
      },
      { status: 202 },
    );
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Project launch failed" },
      { status: 502 },
    );
  }
}
