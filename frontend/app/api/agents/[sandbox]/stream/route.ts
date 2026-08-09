import { spawn, type ChildProcess } from "node:child_process";
import { controlPlaneRoot, hasControlPlaneConfig, isSandboxName, uvExecutable } from "@/lib/control-plane-server";
import { readAgentHistory } from "@/lib/db";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const encoder = new TextEncoder();

function sse(data: unknown, id?: string) {
  return encoder.encode(`${id !== undefined ? `id: ${id}\n` : ""}data: ${JSON.stringify(data)}\n\n`);
}

function eventId(runtimeId: string | undefined, cursor: number | undefined) {
  return runtimeId && cursor !== undefined ? `${runtimeId}:${cursor}` : undefined;
}

function liveStream(
  request: Request,
  sandbox: string,
  after: number,
  runtimeId: string | undefined,
  initial: ReturnType<typeof readAgentHistory> | null,
) {
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
      if (initial) {
        controller.enqueue(sse({
          type: "snapshot",
          data: {
            runtime_id: initial.runtime_id,
            session_id: typeof initial.runtime.session_id === "string" ? initial.runtime.session_id : null,
            turns: initial.turns,
            events: initial.events,
            cursor: initial.cursor,
          },
        }, eventId(initial.runtime_id, initial.cursor)));
      }
      const args = ["run", "gtz", "watch", sandbox, "--after", String(after)];
      if (runtimeId) args.push("--runtime-id", runtimeId);
      const spawned = spawn(
        uvExecutable(),
        args,
        {
        cwd: controlPlaneRoot(),
        env: process.env,
        stdio: ["ignore", "pipe", "pipe"],
        },
      );
      child = spawned;
      controller.enqueue(sse({ type: "connection", data: { mode: "live" } }));
      spawned.stdout?.on("data", (chunk: Buffer) => {
        buffer += chunk.toString("utf8");
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim() || closed) continue;
          try {
            const parsed = JSON.parse(line) as {
              type?: string;
              data?: { cursor?: number; runtime_id?: string };
            };
            const id = parsed.type === "snapshot" || parsed.type === "delta"
              ? eventId(parsed.data?.runtime_id, parsed.data?.cursor)
              : undefined;
            controller.enqueue(sse(parsed, id));
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
  const lastEventId = request.headers.get("last-event-id");
  let after = 0;
  let runtimeId: string | undefined;
  let initial: ReturnType<typeof readAgentHistory> | null = null;
  if (lastEventId) {
    const separator = lastEventId.lastIndexOf(":");
    const parsedAfter = Number.parseInt(lastEventId.slice(separator + 1), 10);
    if (separator > 0 && Number.isFinite(parsedAfter) && parsedAfter >= 0) {
      runtimeId = lastEventId.slice(0, separator);
      after = parsedAfter;
    }
  } else {
    initial = readAgentHistory(sandbox);
    runtimeId = initial.runtime_id || undefined;
    after = initial.cursor;
  }
  const stream = liveStream(request, sandbox, after, runtimeId, initial);
  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      "Connection": "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
