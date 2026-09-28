import { NextRequest, NextResponse } from "next/server";
import { randomBytes, timingSafeEqual } from "node:crypto";

export const ACCESS_COOKIE = "fo_access";
export const REFRESH_COOKIE = "fo_refresh";
export const CSRF_COOKIE = "fo_csrf";
export const WEB_DEVICE_ID = "WEB-CONTROL-TOWER";

export type BackendSession = {
  access_token: string;
  refresh_token: string;
  user_id: string;
  username: string;
  role: string;
  device_id: string;
  must_change_password?: boolean;
};

export function backendBase(request: NextRequest): string {
  const configured =
    process.env.FULFILLOS_SERVER_API_BASE_URL?.replace(/\/$/, "") ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");
  if (configured) return configured;
  return `${request.nextUrl.origin}/api`;
}

export function newCsrfToken(): string {
  return randomBytes(24).toString("base64url");
}

export function csrfMatches(request: NextRequest): boolean {
  const cookie = request.cookies.get(CSRF_COOKIE)?.value ?? "";
  const header = request.headers.get("x-csrf-token") ?? "";
  if (!cookie || !header || cookie.length !== header.length) return false;
  return timingSafeEqual(Buffer.from(cookie), Buffer.from(header));
}

export function setSessionCookies(
  response: NextResponse,
  session: BackendSession,
  csrfToken = newCsrfToken(),
): void {
  const secure = process.env.NODE_ENV === "production";
  response.cookies.set(ACCESS_COOKIE, session.access_token, {
    httpOnly: true,
    secure,
    sameSite: "strict",
    path: "/",
    maxAge: 30 * 60,
  });
  response.cookies.set(REFRESH_COOKIE, session.refresh_token, {
    httpOnly: true,
    secure,
    sameSite: "strict",
    path: "/",
    maxAge: 14 * 24 * 60 * 60,
  });
  response.cookies.set(CSRF_COOKIE, csrfToken, {
    httpOnly: false,
    secure,
    sameSite: "strict",
    path: "/",
    maxAge: 8 * 60 * 60,
  });
}

export function clearSessionCookies(response: NextResponse): void {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE]) {
    response.cookies.set(name, "", {
      httpOnly: name !== CSRF_COOKIE,
      secure: process.env.NODE_ENV === "production",
      sameSite: "strict",
      path: "/",
      maxAge: 0,
    });
  }
}

export async function refreshWebSession(
  request: NextRequest,
): Promise<BackendSession | null> {
  const refreshToken = request.cookies.get(REFRESH_COOKIE)?.value;
  if (!refreshToken) return null;
  const response = await fetch(`${backendBase(request)}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      refresh_token: refreshToken,
      device_id: WEB_DEVICE_ID,
    }),
    cache: "no-store",
  });
  if (!response.ok) return null;
  return (await response.json()) as BackendSession;
}

export async function backendFetch(
  request: NextRequest,
  path: string,
  accessToken: string,
  init: RequestInit = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${accessToken}`);
  headers.set("Accept", "application/json");
  if (init.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${backendBase(request)}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });
}
