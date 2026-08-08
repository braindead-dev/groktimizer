import { spawn, type ChildProcess } from "node:child_process";
import { controlPlaneRoot, hasControlPlaneConfig, isSandboxName, uvExecutable } from "@/lib/control-plane-server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const encoder = new TextEncoder();

function sse(data: unknown) {
  return encoder.encode(`data: ${JSON.stringify(data)}\n\n`);
}

function liveStream(request: Request, sandbox: string) {
  let child: ChildProcess | null = null;
  let closed = false;
  let buffer = "";
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const close = () => {
        if (closed) return;
        closed = true;
        child?.kill("SIGTERM");
        controller.close();
      };
      const spawned = spawn(uvExecutable(), ["run", "gtz", "watch", sandbox], {
        cwd: controlPlaneRoot(),
        env: process.env,
        stdio: ["ignore", "pipe", "pipe"],
      });
      child = spawned;
      controller.enqueue(sse({ type: "connection", data: { mode: "live" } }));
      spawned.stdout?.on("data", (chunk: Buffer) => {
        buffer += chunk.toString("utf8");
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim() || closed) continue;
          try {
            controller.enqueue(sse(JSON.parse(line)));
          } catch {
            controller.enqueue(sse({ type: "error", data: { message: "Invalid control-plane event" } }));
          }
        }
      });
      spawned.on("error", () => {
        if (!closed) controller.enqueue(sse({ type: "error", data: { message: "Agent stream unavailable" } }));
        close();
      });
      spawned.on("exit", close);
      request.signal.addEventListener("abort", close, { once: true });
    },
    cancel() {
      closed = true;
      child?.kill("SIGTERM");
    },
  });
  return stream;
}

export async function GET(request: Request, context: { params: Promise<{ sandbox: string }> }) {
  const { sandbox } = await context.params;
  if (!isSandboxName(sandbox)) return new Response("Invalid sandbox", { status: 400 });
  if (!hasControlPlaneConfig()) return new Response("Control plane is not configured", { status: 503 });
  const stream = liveStream(request, sandbox);
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
