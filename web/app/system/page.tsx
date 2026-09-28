"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  getAuditEvents,
  getEmployees,
  getMyPermissions,
  getSystemHealth,
  getWebSession,
  managerLogin,
  managerLogout,
  setRolePermission,
  setUserPermission,
  type AuditEvent,
  type EffectivePermissions,
  type Employee,
  type SystemHealth,
} from "../../lib/api";

const roles = [
  "PICKER",
  "SENIOR_PICKER",
  "QUALITY",
  "QUALITY_LEADER",
  "TEAM_LEADER",
  "SUPERVISOR",
  "RECEIVER",
  "INVENTORY",
] as const;

const permissionCatalog = [
  "operations.read",
  "operations.manage",
  "employees.read",
  "employees.write",
  "quality.read",
  "quality.inspect",
  "quality.manage",
  "attendance.approve",
  "shifts.manage",
  "replenishment.execute",
  "replenishment.manage",
  "payroll.read",
  "payroll.adjust",
  "promotions.manage",
  "password_reset.resolve",
  "permissions.manage",
  "audit.read",
] as const;

function readable(value: string) {
  return value
    .replaceAll("_", " ")
    .replaceAll(".", " · ")
    .toLowerCase()
    .replace(/(^|\s)\S/g, (letter) => letter.toUpperCase());
}

export default function SystemPage() {
  const [session, setSession] = useState("");
  const [authChecking, setAuthChecking] = useState(true);
  const [loginUser, setLoginUser] = useState("supervisor");
  const [loginPassword, setLoginPassword] = useState("");
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [permissions, setPermissions] = useState<EffectivePermissions | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [auditEntity, setAuditEntity] = useState("");
  const [roleGrant, setRoleGrant] = useState({
    role: "TEAM_LEADER",
    permission: "operations.manage",
    allowed: true,
  });
  const [userGrant, setUserGrant] = useState({
    user_id: "",
    permission: "operations.read",
    allowed: true,
  });

  useEffect(() => {
    void getWebSession()
      .then((value) => {
        if (
          value.authenticated &&
          ["SUPERVISOR", "ADMIN"].includes(value.role.toUpperCase())
        ) {
          setSession("session");
        }
      })
      .finally(() => setAuthChecking(false));
  }, []);

  async function refresh(activeSession = session) {
    if (!activeSession) return;
    try {
      const [healthData, permissionData, auditData, peopleData] = await Promise.all([
        getSystemHealth(activeSession),
        getMyPermissions(activeSession),
        getAuditEvents(activeSession, {
          entity_type: auditEntity || undefined,
          limit: 150,
        }),
        getEmployees(activeSession),
      ]);
      setHealth(healthData);
      setPermissions(permissionData);
      setEvents(auditData.events);
      setEmployees(peopleData.employees);
      if (!userGrant.user_id && peopleData.employees.length > 0) {
        setUserGrant((current) => ({
          ...current,
          user_id: peopleData.employees[0].user_id,
        }));
      }
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not load administration data");
    }
  }

  useEffect(() => {
    if (!session) return;
    void refresh(session);
    const timer = window.setInterval(() => void refresh(session), 10_000);
    return () => window.clearInterval(timer);
  }, [session, auditEntity]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await managerLogin(loginUser, loginPassword);
      if (!["SUPERVISOR", "ADMIN"].includes(result.role.toUpperCase())) {
        await managerLogout();
        throw new Error("Supervisor or admin role required");
      }
      setSession("session");
      setLoginPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function submitRoleGrant(event: FormEvent) {
    event.preventDefault();
    if (!session) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await setRolePermission(
        session,
        roleGrant.role,
        roleGrant.permission,
        roleGrant.allowed,
      );
      setNotice(
        `${result.role}: ${result.permission} → ${result.allowed ? "allowed" : "denied"}`,
      );
      await refresh(session);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update role permission");
    } finally {
      setBusy(false);
    }
  }

  async function submitUserGrant(event: FormEvent) {
    event.preventDefault();
    if (!session || !userGrant.user_id) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await setUserPermission(
        session,
        userGrant.user_id,
        userGrant.permission,
        userGrant.allowed,
      );
      const employee = employees.find((item) => item.user_id === result.user_id);
      setNotice(
        `@${employee?.username ?? result.user_id}: ${result.permission} → ${result.allowed ? "allowed" : "denied"}`,
      );
      await refresh(session);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not update user permission");
    } finally {
      setBusy(false);
    }
  }

  const outboxTotal = useMemo(
    () => (health?.outbox.pending ?? 0) + (health?.outbox.failed ?? 0),
    [health],
  );

  if (authChecking) {
    return <main className="shell"><section className="panel authPanel">Checking secure session…</section></main>;
  }

  if (!session) {
    return (
      <main className="shell">
        <section className="panel authPanel">
          <p className="eyebrow">ADMINISTRATION</p>
          <h1 className="peopleTitle">Admin & Audit</h1>
          <p className="subtitle">
            System health, permission overrides and the sensitive-change audit trail.
          </p>
          <form className="formStack" onSubmit={login}>
            <label><span>Supervisor username</span><input required value={loginUser} onChange={(e) => setLoginUser(e.target.value)} /></label>
            <label><span>PIN / password</span><input required type="password" value={loginPassword} onChange={(e) => setLoginPassword(e.target.value)} /></label>
            {error && <div className="alert">{error}</div>}
            <button className="primaryButton" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="shell operationsShell">
      <header className="peopleHeader">
        <div>
          <p className="eyebrow">FULFILLOS · ADMINISTRATION</p>
          <h1 className="peopleTitle">Admin & Audit</h1>
          <p className="subtitle">
            The place for system health, outbox/telemetry status, permission overrides and sensitive-change history.
          </p>
        </div>
        <div className="peopleActions">
          <button onClick={() => void refresh()} disabled={busy}>Refresh</button>
          <button onClick={() => { void managerLogout(); setSession(""); }}>Sign out</button>
        </div>
      </header>

      {notice && <section className="noticeBox">{notice}</section>}
      {error && <section className="alert">{error}</section>}

      <nav className="sectionJumpNav" aria-label="Administration sections">
        <a href="#health">System health</a>
        <a href="#permissions">Permissions</a>
        <a href="#audit">Audit trail</a>
      </nav>

      <section id="health" className="headlineGrid opsHeadline">
        <article className="heroCard">
          <span>Database</span>
          <strong className="compactHeroValue">{health?.database ?? "—"}</strong>
          <small>API v{health?.version ?? "—"}</small>
        </article>
        <article className={`heroCard ${outboxTotal > 0 ? "critical" : ""}`}>
          <span>Outbox pending / failed</span>
          <strong>{health ? `${health.outbox.pending} / ${health.outbox.failed}` : "—"}</strong>
          <small>{health?.outbox.published ?? 0} published</small>
        </article>
        <article className="heroCard">
          <span>Observability</span>
          <strong className="compactHeroValue">{health?.otel_exporter_configured ? "OTLP on" : "Local only"}</strong>
          <small>Incident webhook: {health?.incident_webhook_configured ? "configured" : "not configured"}</small>
        </article>
      </section>

      <section id="permissions" className="panel opsSection">
        <div className="panelHeading">
          <div><p className="eyebrow">ACCESS CONTROL</p><h2>Permission overrides</h2></div>
          <span className="chip">{permissions?.role ?? "—"}</span>
        </div>
        <p className="sectionHelp">
          Defaults come from each role. These controls create explicit allow/deny overrides and every change is audited.
        </p>
        <div className="managerForms">
          <form className="managerForm" onSubmit={submitRoleGrant}>
            <h3>Role override</h3>
            <label><span>Role</span><select value={roleGrant.role} onChange={(e) => setRoleGrant({...roleGrant, role:e.target.value})}>{roles.map((role) => <option key={role}>{role}</option>)}</select></label>
            <label><span>Permission</span><select value={roleGrant.permission} onChange={(e) => setRoleGrant({...roleGrant, permission:e.target.value})}>{permissionCatalog.map((permission) => <option key={permission}>{permission}</option>)}</select></label>
            <label><span>Decision</span><select value={roleGrant.allowed ? "ALLOW" : "DENY"} onChange={(e) => setRoleGrant({...roleGrant, allowed:e.target.value === "ALLOW"})}><option>ALLOW</option><option>DENY</option></select></label>
            <button className="primaryButton" disabled={busy}>Save role override</button>
          </form>

          <form className="managerForm" onSubmit={submitUserGrant}>
            <h3>User override</h3>
            <label><span>Employee</span><select value={userGrant.user_id} onChange={(e) => setUserGrant({...userGrant, user_id:e.target.value})}>{employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.profile?.full_name ?? employee.username} · @{employee.username}</option>)}</select></label>
            <label><span>Permission</span><select value={userGrant.permission} onChange={(e) => setUserGrant({...userGrant, permission:e.target.value})}>{permissionCatalog.map((permission) => <option key={permission}>{permission}</option>)}</select></label>
            <label><span>Decision</span><select value={userGrant.allowed ? "ALLOW" : "DENY"} onChange={(e) => setUserGrant({...userGrant, allowed:e.target.value === "ALLOW"})}><option>ALLOW</option><option>DENY</option></select></label>
            <button className="primaryButton" disabled={busy || !userGrant.user_id}>Save user override</button>
          </form>

          <article className="managerForm">
            <h3>Your effective permissions</h3>
            <div className="permissionChips">
              {(permissions?.permissions ?? []).map((permission) => (
                <span className="chip" key={permission}>{permission}</span>
              ))}
            </div>
            <p className="policyNote">
              User overrides take precedence over role overrides, which take precedence over built-in defaults.
            </p>
          </article>
        </div>
      </section>

      <section id="audit" className="panel opsSection">
        <div className="panelHeading">
          <div><p className="eyebrow">AUDIT</p><h2>Sensitive-change trail</h2></div>
          <span className="chip">{events.length} events</span>
        </div>
        <div className="searchBar compactSearch">
          <select value={auditEntity} onChange={(e) => setAuditEntity(e.target.value)}>
            <option value="">All entity types</option>
            <option>USER</option>
            <option>ATTENDANCE</option>
            <option>PAY_ADJUSTMENT</option>
            <option>PAYROLL_POLICY</option>
            <option>PERFORMANCE_EVENT</option>
            <option>SHIFT_TEMPLATE</option>
            <option>SHIFT_ASSIGNMENT</option>
            <option>ROLE_PERMISSION</option>
            <option>USER_PERMISSION</option>
          </select>
          <button onClick={() => void refresh()} disabled={busy}>Refresh audit</button>
        </div>
        <div className="tableWrap">
          <table>
            <thead><tr><th>Time</th><th>Action</th><th>Entity</th><th>Actor</th><th>Reason</th></tr></thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.id}>
                  <td>{new Date(event.created_at).toLocaleString()}</td>
                  <td><strong>{readable(event.action)}</strong></td>
                  <td>{event.entity_type} · <code>{event.entity_id.slice(0, 12)}</code></td>
                  <td><code>{event.actor_user_id?.slice(0, 12) ?? "system"}</code></td>
                  <td>{event.reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {events.length === 0 && <div className="empty compactEmpty"><span>✓</span><div><strong>No matching audit events</strong><p>Try a different entity filter.</p></div></div>}
      </section>
    </main>
  );
}
