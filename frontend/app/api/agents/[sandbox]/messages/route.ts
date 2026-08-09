import { NextResponse } from "next/server";
import { hasControlPlaneConfig, isSandboxName, runGtz } from "@/lib/control-plane-server";

export const runtime = "nodejs";

export async function POST(request: Request, context: { params: Promise<{ sandbox: string }> }) {
  const { sandbox } = await context.params;
  if (!isSandboxName(sandbox)) {
    return NextResponse.json({ error: "Invalid sandbox" }, { status: 400 });
  }
  if (!hasControlPlaneConfig()) {
    return NextResponse.json({ error: "Control plane is not configured" }, { status: 503 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }
  const message = typeof body === "object" && body !== null && "message" in body
    ? (body as { message?: unknown }).message
    : null;
  const clientId = typeof body === "object" && body !== null && "clientId" in body
    ? (body as { clientId?: unknown }).clientId
    : null;
  const mode = typeof body === "object" && body !== null && "mode" in body
    ? (body as { mode?: unknown }).mode
    : "queue";
  const retry = typeof body === "object" && body !== null && "retry" in body
    ? (body as { retry?: unknown }).retry === true
    : false;
  if (typeof message !== "string" || !message.trim() || message.length > 4_000) {
    return NextResponse.json({ error: "Message must contain 1–4,000 characters" }, { status: 400 });
  }
  if (typeof clientId !== "string" || !clientId.trim() || clientId.length > 160) {
    return NextResponse.json({ error: "A valid client message id is required" }, { status: 400 });
  }
  if (mode !== "queue" && mode !== "interrupt") {
    return NextResponse.json({ error: "Mode must be queue or interrupt" }, { status: 400 });
  }

  try {
    const args = ["send", sandbox, message.trim(), "--client-id", clientId.trim()];
    if (mode === "interrupt") args.push("--interrupt");
    if (retry) args.push("--retry");
    const stdout = await runGtz(args, 30_000);
    const parsed = JSON.parse(stdout.trim().split("\n").at(-1) ?? "") as {
      id: string;
      turn_id: string;
      status: "queued" | "running";
      mode: "queue" | "interrupt";
      turn: Record<string, unknown>;
    };
    return NextResponse.json({
      sent: true,
      id: parsed.id,
      turnId: parsed.turn_id,
      status: parsed.status,
      mode: parsed.mode,
      turn: parsed.turn,
    });
  } catch (error) {
    const detail = [
      error instanceof Error ? error.message : String(error),
      typeof error === "object" && error !== null && "stderr" in error
        ? String((error as { stderr?: unknown }).stderr ?? "")
        : "",
    ].join("\n");
    if (detail.includes("runner is unavailable") || detail.includes("repair the sandbox")) {
      return NextResponse.json(
        { error: "The agent runner needs repair before this message can be delivered.", code: "runner_unavailable" },
        { status: 409 },
      );
    }
    const timedOut = detail.includes("timed out") || detail.includes("ETIMEDOUT");
    return NextResponse.json(
      {
        error: timedOut
          ? "Delivery could not be confirmed. Retrying is safe and will reuse the same message id."
          : "Steering delivery could not be confirmed.",
        code: "delivery_unknown",
      },
      { status: timedOut ? 504 : 502 },
    );
  }
}
