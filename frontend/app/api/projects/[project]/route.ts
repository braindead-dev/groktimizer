import { NextResponse } from "next/server";
import type { ControlPlaneSnapshot } from "@/lib/control-plane-types";
import { hasControlPlaneConfig, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PROJECT_NAME = /^[a-z0-9]{1,24}$/;

export async function DELETE(
  _request: Request,
  context: { params: Promise<{ project: string }> },
) {
  const { project } = await context.params;
  if (!PROJECT_NAME.test(project)) {
    return NextResponse.json({ error: "Invalid project" }, { status: 400 });
  }
  if (!hasControlPlaneConfig()) {
    return NextResponse.json({ error: "Control plane is not configured" }, { status: 503 });
  }

  try {
    const before = JSON.parse(await runGtz(["snapshot"])) as ControlPlaneSnapshot;
    const beforeProject = before.projects.find((candidate) => candidate.project === project);
    if (!beforeProject) {
      return NextResponse.json({ error: "Project is not attached to this control plane" }, { status: 404 });
    }

    await runGtz(["stop", "--project", project], 120_000);
    for (let attempt = 0; attempt < 8; attempt += 1) {
      const current = JSON.parse(await runGtz(["snapshot"])) as ControlPlaneSnapshot;
      const currentProject = current.projects.find((candidate) => candidate.project === project);
      if (!currentProject || currentProject.agents.length === 0) {
        return NextResponse.json({ deleted: true, project, sandboxes: beforeProject.agents.length });
      }
      await new Promise((resolve) => setTimeout(resolve, 1_000));
    }

    return NextResponse.json(
      { error: "Sandbox deletion is still propagating; refresh shortly" },
      { status: 202 },
    );
  } catch {
    return NextResponse.json({ error: "Project deletion failed" }, { status: 502 });
  }
}
