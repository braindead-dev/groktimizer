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
  if (typeof message !== "string" || !message.trim() || message.length > 4_000) {
    return NextResponse.json({ error: "Message must contain 1–4,000 characters" }, { status: 400 });
  }

  try {
    const stdout = await runGtz(["send", sandbox, message.trim()], 30_000);
    let id: string | null = null;
    try {
      const parsed = JSON.parse(stdout.trim().split("\n").at(-1) ?? "");
      if (typeof parsed?.id === "string") id = parsed.id;
    } catch {
      // older gtz builds print plain "sent"; the message still went through
    }
    return NextResponse.json({ sent: true, id });
  } catch {
    return NextResponse.json({ error: "Steering delivery failed" }, { status: 502 });
  }
}
