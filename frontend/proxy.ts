import { timingSafeEqual } from "node:crypto";
import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";

function equal(left: string, right: string) {
  const leftBytes = Buffer.from(left);
  const rightBytes = Buffer.from(right);
  return leftBytes.length === rightBytes.length && timingSafeEqual(leftBytes, rightBytes);
}

function credentials(request: NextRequest) {
  const authorization = request.headers.get("authorization");
  if (!authorization?.startsWith("Basic ")) return null;
  try {
    const decoded = Buffer.from(authorization.slice(6), "base64").toString("utf8");
    const separator = decoded.indexOf(":");
    if (separator < 0) return null;
    return { username: decoded.slice(0, separator), password: decoded.slice(separator + 1) };
  } catch {
    return null;
  }
}

export function proxy(request: NextRequest) {
  const expectedUsername = process.env.GTZ_DASHBOARD_USERNAME?.trim();
  const expectedPassword = process.env.GTZ_DASHBOARD_PASSWORD;
  if (!expectedUsername && !expectedPassword) return NextResponse.next();
  if (!expectedUsername || !expectedPassword) {
    return new NextResponse("Dashboard authentication is misconfigured", { status: 503 });
  }

  const supplied = credentials(request);
  if (
    supplied &&
    equal(supplied.username, expectedUsername) &&
    equal(supplied.password, expectedPassword)
  ) {
    return NextResponse.next();
  }
  return new NextResponse("Authentication required", {
    status: 401,
    headers: {
      "Cache-Control": "no-store",
      "WWW-Authenticate": 'Basic realm="Groktimizer", charset="UTF-8"',
    },
  });
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|brand/|install\\.sh|favicon\\.ico).*)"],
};

