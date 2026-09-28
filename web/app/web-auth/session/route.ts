import { NextRequest, NextResponse } from "next/server";
import {
  ACCESS_COOKIE,
  backendFetch,
  clearSessionCookies,
  refreshWebSession,
  setSessionCookies,
} from "../../../lib/server-session";

export async function GET(request: NextRequest) {
  let accessToken = request.cookies.get(ACCESS_COOKIE)?.value ?? "";
  let refreshed = null;

  let upstream = accessToken
    ? await backendFetch(request, "/me", accessToken, { method: "GET" })
    : new Response(null, { status: 401 });

  if (upstream.status === 401) {
    refreshed = await refreshWebSession(request);
    if (refreshed) {
      accessToken = refreshed.access_token;
      upstream = await backendFetch(request, "/me", accessToken, { method: "GET" });
    }
  }

  if (!upstream.ok) {
    const result = NextResponse.json({ authenticated: false }, { status: 401 });
    clearSessionCookies(result);
    return result;
  }

  const body = await upstream.json();
  const result = NextResponse.json({
    authenticated: true,
    user_id: body.user_id,
    username: body.username,
    role: body.role,
    device_id: body.device_id,
  });
  if (refreshed) setSessionCookies(result, refreshed);
  return result;
}
