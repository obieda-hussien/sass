import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  CSRF_COOKIE,
  backendFetch,
  clearSessionCookies,
  csrfMatches,
  refreshWebSession,
  setSessionCookies,
} from "../../../lib/server-session";

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const method = request.method.toUpperCase();

  if (!SAFE_METHODS.has(method) && !csrfMatches(request)) {
    return NextResponse.json(
      { detail: { code: "CSRF_REJECTED", message: "CSRF token missing or invalid." } },
      { status: 403, headers: { "Cache-Control": "no-store" } },
    );
  }

  const suffix = "/" + path.map(encodeURIComponent).join("/");
  const query = request.nextUrl.search;
  const upstreamPath = suffix + query;

  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value ?? "";
  let refreshed = null;
  if (!accessToken) {
    refreshed = await refreshWebSession(request);
    accessToken = refreshed?.access_token ?? "";
  }
  if (!accessToken) {
    const denied = NextResponse.json({ detail: "Authentication required" }, { status: 401 });
    clearSessionCookies(denied);
    return denied;
  }

  const body = SAFE_METHODS.has(method) ? undefined : await request.arrayBuffer();
  const contentType = request.headers.get("content-type");
  let upstream = await backendFetch(request, upstreamPath, accessToken, {
    method,
    body,
    headers: contentType ? { "Content-Type": contentType } : undefined,
  });

  if (upstream.status === 401 && !refreshed) {
    refreshed = await refreshWebSession(request);
    if (refreshed) {
      accessToken = refreshed.access_token;
      upstream = await backendFetch(request, upstreamPath, accessToken, {
        method,
        body,
        headers: contentType ? { "Content-Type": contentType } : undefined,
      });
    }
  }

  const raw = await upstream.arrayBuffer();
  const response = new NextResponse(raw, {
    status: upstream.status,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "application/json",
      "Cache-Control": "no-store",
    },
  });

  if (refreshed) {
    setSessionCookies(
      response,
      refreshed,
      request.cookies.get(CSRF_COOKIE)?.value,
    );
  }
  if (upstream.status === 401) clearSessionCookies(response);
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
