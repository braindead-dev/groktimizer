import "server-only";

const DEFAULT_TIMEOUT_MS = 30_000;

interface BackendConfig {
  baseUrl: URL;
  token: string;
}

function backendConfig(): BackendConfig {
  const rawUrl = process.env.GTZ_CONTROL_PLANE_URL?.trim();
  const token = process.env.GTZ_CONTROL_PLANE_TOKEN?.trim();
  if (!rawUrl || !token) {
    throw new Error(
      "GTZ_CONTROL_PLANE_URL and GTZ_CONTROL_PLANE_TOKEN must both be configured",
    );
  }
  const baseUrl = new URL(rawUrl);
  const local = ["localhost", "127.0.0.1", "::1"].includes(baseUrl.hostname);
  if (baseUrl.protocol !== "https:" && !(local && baseUrl.protocol === "http:")) {
    throw new Error("GTZ_CONTROL_PLANE_URL must use HTTPS");
  }
  baseUrl.pathname = baseUrl.pathname.replace(/\/$/, "");
  return { baseUrl, token };
}

export function hasRemoteControlPlane() {
  return Boolean(
    process.env.GTZ_CONTROL_PLANE_URL?.trim() ||
      process.env.GTZ_CONTROL_PLANE_TOKEN?.trim(),
  );
}

export async function controlPlaneFetch(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
) {
  const { baseUrl, token } = backendConfig();
  const url = new URL(path, `${baseUrl.toString().replace(/\/$/, "")}/`);
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  headers.set("Accept", "application/json");
  const signal = init.signal ?? AbortSignal.timeout(timeoutMs);
  return fetch(url, {
    ...init,
    headers,
    signal,
    cache: "no-store",
  });
}

export function backendResponse(response: Response) {
  return new Response(response.body, {
    status: response.status,
    headers: {
      "Content-Type": response.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });
}

export function validateBackendStreamUrl(value: string) {
  const { baseUrl } = backendConfig();
  const url = new URL(value);
  if (url.origin !== baseUrl.origin || !url.pathname.startsWith("/v1/agents/")) {
    throw new Error("The control plane returned an invalid stream URL");
  }
  return url.toString();
}
