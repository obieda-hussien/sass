const { test, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { NextRequest } = require("next/server");
const fromBuild = (file) => require(path.join(process.env.TEST_BUILD_DIR, file));
const sessionRoute = fromBuild("app/web-auth/session/route.js");
const proxyRoute = fromBuild("app/web-api/[...path]/route.js");
const api = fromBuild("lib/api.js");
const { csrfMatches } = fromBuild("lib/server-session.js");
const originalFetch = global.fetch;
afterEach(() => { global.fetch = originalFetch; delete global.document; });

const payload = { label: "RETRY-001", shipment_type: "VENDOR", storage_domain: "AMBIENT",
  lines: [{ product_id: "6221073000849", expected_qty: 1 }] };
const rejection = () => Response.json({ detail: { code: "CSRF_REJECTED" } }, { status: 403 });

// Exercise the client through the actual BFF routes, including Set-Cookie application.
function warehouseBrowser(cookies, options = {}) {
  const jar = new Map(Object.entries(cookies));
  const calls = { mutations: 0, writes: 0, sessions: 0, refreshes: 0, bodies: [] };
  let firstRead = options.staleRead;
  Object.defineProperty(global, "document", { configurable: true, value: {
    get cookie() {
      if (firstRead) { const stale = firstRead; firstRead = null; return `fo_csrf=${stale}`; }
      return jar.has("fo_csrf") ? `fo_csrf=${jar.get("fo_csrf")}` : "";
    },
  } });
  global.fetch = async (url, init = {}) => {
    if (String(url).startsWith("/web-")) {
      const headers = new Headers(init.headers);
      headers.set("cookie", [...jar].map(([key, value]) => `${key}=${value}`).join("; "));
      const request = new NextRequest(`https://warehouse.example${url}`, { ...init, headers });
      let response;
      if (url === "/web-auth/session") {
        calls.sessions++;
        response = await sessionRoute.GET(request);
      } else {
        calls.mutations++;
        response = await proxyRoute.POST(request, { params: Promise.resolve({ path: ["ops", "shipments"] }) });
      }
      for (const cookie of response.cookies.getAll()) {
        if (cookie.maxAge === 0) jar.delete(cookie.name);
        else jar.set(cookie.name, cookie.value);
      }
      return response;
    }
    const pathname = new URL(url).pathname;
    if (pathname === "/api/auth/refresh") {
      calls.refreshes++;
      return options.expired ? new Response(null, { status: 401 }) : Response.json({
        access_token: "renewed", refresh_token: "new-refresh", user_id: "u1", role: "SUPERVISOR",
      });
    }
    if (pathname === "/api/me") return Response.json({ user_id: "u1", role: "SUPERVISOR" });
    assert.equal(pathname, "/api/ops/shipments");
    calls.writes++;
    calls.bodies.push(JSON.parse(new TextDecoder().decode(init.body)));
    return Response.json({ id: "shipment-id", label: payload.label });
  };
  return { calls, jar };
}

test("missing CSRF with a valid login is repaired before creating exactly one shipment", async () => {
  const { calls, jar } = warehouseBrowser({ fo_access: "valid" });
  assert.equal((await api.createShipment("session", payload)).id, "shipment-id");
  assert.equal(calls.sessions, 1);
  assert.equal(calls.writes, 1);
  assert.deepEqual(calls.bodies, [payload]);
  assert.ok(jar.get("fo_csrf"));
});

test("a stale header is rejected before forwarding and recovered with one bounded retry", async () => {
  const { calls } = warehouseBrowser({ fo_access: "valid", fo_csrf: "current" }, { staleRead: "old-token" });
  await api.createShipment("session", payload);
  assert.equal(calls.mutations, 2);
  assert.equal(calls.sessions, 1);
  assert.equal(calls.writes, 1);
  assert.deepEqual(calls.bodies, [payload]);
});

test("an expired access cookie can refresh without discarding a valid refresh cookie", async () => {
  const { calls, jar } = warehouseBrowser({ fo_refresh: "valid-refresh", fo_csrf: "token" });
  await api.createShipment("session", payload);
  assert.equal(calls.refreshes, 1);
  assert.equal(calls.writes, 1);
  assert.equal(jar.get("fo_access"), "renewed");
});

test("an expired session stops before the mutation", async () => {
  const { calls } = warehouseBrowser({ fo_refresh: "expired" }, { expired: true });
  await assert.rejects(api.createShipment("session", payload), /session has expired/);
  assert.equal(calls.mutations, 0);
  assert.equal(calls.writes, 0);
});

test("session checks preserve a usable token and mark token responses as uncacheable", async () => {
  warehouseBrowser({ fo_access: "valid", fo_csrf: "existing" });
  const response = await global.fetch("/web-auth/session");
  assert.equal((await response.json()).csrf_token, "existing");
  assert.equal(response.headers.get("cache-control"), "no-store");
  const cookie = response.cookies.get("fo_csrf");
  assert.equal(cookie.maxAge, 14 * 24 * 60 * 60);
  assert.equal(cookie.sameSite, "strict");
});

test("missing or forged tokens never reach the backend", async () => {
  let upstreamCalls = 0;
  global.fetch = async () => { upstreamCalls++; throw new Error("must not forward"); };
  for (const headers of [{ cookie: "fo_access=valid" }, { cookie: "fo_access=valid; fo_csrf=correct", "x-csrf-token": "forged!" }]) {
    const response = await proxyRoute.POST(new NextRequest("https://warehouse.example/web-api/ops/shipments", { method: "POST", headers }),
      { params: Promise.resolve({ path: ["ops", "shipments"] }) });
    assert.equal(response.status, 403);
    assert.equal((await response.json()).detail.code, "CSRF_REJECTED");
  }
  assert.equal(upstreamCalls, 0);
});

test("a non-ASCII token of the same character length is rejected without crashing", () => {
  const request = new NextRequest("https://warehouse.example", { headers: { cookie: "fo_csrf=é", "x-csrf-token": "a" } });
  assert.equal(csrfMatches(request), false);
});

test("CSRF retry is bounded if cookies cannot be restored", async () => {
  global.document = { cookie: "fo_csrf=old" };
  let mutations = 0, sessions = 0;
  global.fetch = async (url) => {
    if (url === "/web-auth/session") { sessions++; return Response.json({ authenticated: true, csrf_token: "new" }); }
    mutations++; return rejection();
  };
  await assert.rejects(api.createShipment("session", payload), /could not be renewed/);
  assert.equal(mutations, 2);
  assert.equal(sessions, 1);
});

test("network errors never trigger a mutation replay", async () => {
  global.document = { cookie: "fo_csrf=valid" };
  let requests = 0;
  global.fetch = async () => { requests++; throw new TypeError("Network unavailable"); };
  await assert.rejects(api.createShipment("session", payload), /Network unavailable/);
  assert.equal(requests, 1);
});

test("a normal backend error is returned without CSRF recovery or replay", async () => {
  global.document = { cookie: "fo_csrf=valid" };
  let requests = 0;
  global.fetch = async () => { requests++; return Response.json({ detail: { code: "PRODUCT_NOT_FOUND", message: "Register this item first" } }, { status: 409 }); };
  await assert.rejects(api.createShipment("session", payload), /Register this item first/);
  assert.equal(requests, 1);
});
