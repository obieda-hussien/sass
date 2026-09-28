import { NextRequest, NextResponse } from "next/server";
import {
  WEB_DEVICE_ID,
  backendBase,
  clearSessionCookies,
  setSessionCookies,
  type BackendSession,
} from "../../../lib/server-session";

export async function POST(request: NextRequest) {
  const payload = await request.json().catch(() => ({}));
  const response = await fetch(`${backendBase(request)}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      username: String(payload.username ?? "").trim(),
      password: String(payload.password ?? ""),
      device_id: WEB_DEVICE_ID,
      app_version: "web-0.5.1",
    }),
    cache: "no-store",
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const result = NextResponse.json(body, { status: response.status });
    clearSessionCookies(result);
    return result;
  }

  const session = body as BackendSession;
  if (session.must_change_password) {
    const result = NextResponse.json(
      {
        detail: {
          code: "PASSWORD_CHANGE_REQUIRED",
          message: "This account must set a personal PIN on the PDA before using the web console.",
        },
      },
      { status: 428 },
    );
    clearSessionCookies(result);
    return result;
  }

  const result = NextResponse.json({
    authenticated: true,
    user_id: session.user_id,
    username: session.username,
    role: session.role,
  });
  setSessionCookies(result, session);
  return result;
}
