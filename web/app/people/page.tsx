"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  createEmployee,
  getEmployees,
  getPasswordResets,
  issueTemporaryPassword,
  managerLogin,
  type Employee,
  type PasswordResetItem,
} from "../../lib/api";

type CreateForm = {
  username: string;
  password: string;
  employee_code: string;
  full_name: string;
  email: string;
  phone: string;
  address: string;
  role: string;
  job_title: string;
  department: string;
  base_salary: string;
  overtime_rate: string;
  grace_minutes: string;
};

const emptyForm: CreateForm = {
  username: "",
  password: "",
  employee_code: "",
  full_name: "",
  email: "",
  phone: "",
  address: "",
  role: "PICKER",
  job_title: "Picker",
  department: "Operations",
  base_salary: "",
  overtime_rate: "",
  grace_minutes: "10",
};

function money(cents: number, currency = "EGP") {
  return new Intl.NumberFormat("en-EG", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

export default function PeoplePage() {
  const [token, setToken] = useState("");
  const [loginUser, setLoginUser] = useState("supervisor");
  const [loginPassword, setLoginPassword] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [resets, setResets] = useState<PasswordResetItem[]>([]);
  const [form, setForm] = useState<CreateForm>(emptyForm);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("fulfillos_admin_token");
    if (saved) setToken(saved);
  }, []);

  async function refresh(activeToken = token) {
    if (!activeToken) return;
    try {
      const [people, resetData] = await Promise.all([
        getEmployees(activeToken),
        getPasswordResets(activeToken),
      ]);
      setEmployees(people.employees);
      setResets(resetData.requests);
      setError("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load workforce data");
    }
  }

  useEffect(() => {
    if (token) void refresh(token);
  }, [token]);

  async function login(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await managerLogin(loginUser, loginPassword);
      if (!["SUPERVISOR", "ADMIN"].includes(result.role.toUpperCase())) {
        throw new Error("Supervisor or admin role required");
      }
      window.localStorage.setItem("fulfillos_admin_token", result.access_token);
      setToken(result.access_token);
      setLoginPassword("");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function submitEmployee(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await createEmployee(token, {
        username: form.username,
        password: form.password || null,
        employee_code: form.employee_code,
        full_name: form.full_name,
        email: form.email || null,
        phone: form.phone || null,
        address: form.address || null,
        role: form.role,
        job_title: form.job_title,
        department: form.department,
        base_salary_cents: Math.round(Number(form.base_salary || "0") * 100),
        overtime_rate_cents_per_hour: Math.round(Number(form.overtime_rate || "0") * 100),
        grace_minutes: Number(form.grace_minutes || "10"),
        currency: "EGP",
      });
      setForm(emptyForm);
      setNotice(
        created.temporary_password
          ? `Employee created. Temporary password: ${created.temporary_password}`
          : "Employee created successfully.",
      );
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create employee");
    } finally {
      setBusy(false);
    }
  }

  async function resolveReset(item: PasswordResetItem) {
    if (!token) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await issueTemporaryPassword(token, item.id);
      setNotice(
        `Temporary password for ${item.username ?? item.full_name ?? "employee"}: ${result.temporary_password}`,
      );
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reset password");
    } finally {
      setBusy(false);
    }
  }

  const totals = useMemo(() => {
    return employees.reduce(
      (acc, item) => {
        acc.people += 1;
        acc.orders += item.payroll?.completed_orders ?? 0;
        acc.overtime += item.payroll?.overtime_minutes ?? 0;
        acc.late += item.payroll?.late_minutes ?? 0;
        return acc;
      },
      { people: 0, orders: 0, overtime: 0, late: 0 },
    );
  }, [employees]);

  if (!token) {
    return (
      <main className="shell peopleShell">
        <div className="peopleTopline">
          <a href="/">← Control Tower</a>
        </div>
        <section className="panel authPanel">
          <p className="eyebrow">WORKFORCE ADMIN</p>
          <h1 className="peopleTitle">People & Payroll</h1>
          <p className="subtitle">
            Employee records, attendance, overtime, operational metrics and password recovery.
          </p>
          <form className="formStack" onSubmit={login}>
            <label>
              <span>Supervisor username</span>
              <input value={loginUser} onChange={(e) => setLoginUser(e.target.value)} required />
            </label>
            <label>
              <span>Password</span>
              <input
                type="password"
                value={loginPassword}
                onChange={(e) => setLoginPassword(e.target.value)}
                required
              />
            </label>
            {error && <div className="alert">{error}</div>}
            <button className="primaryButton" disabled={busy}>
              {busy ? "Signing in…" : "Sign in"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="shell peopleShell">
      <header className="peopleHeader">
        <div>
          <div className="peopleTopline">
            <a href="/">← Control Tower</a>
          </div>
          <p className="eyebrow">FULFILLOS · PEOPLE</p>
          <h1 className="peopleTitle">People & Payroll</h1>
          <p className="subtitle">
            Operational performance is visible, but pay changes require explicit approved adjustments.
          </p>
        </div>
        <div className="peopleActions">
          <button onClick={() => void refresh()} disabled={busy}>Refresh</button>
          <button
            onClick={() => {
              window.localStorage.removeItem("fulfillos_admin_token");
              setToken("");
              setEmployees([]);
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      {notice && <section className="noticeBox">{notice}</section>}
      {error && <section className="alert">{error}</section>}

      <section className="headlineGrid workforceStats">
        <article className="heroCard">
          <span>Employees</span>
          <strong>{totals.people}</strong>
          <small>Active profiles in the workforce system</small>
        </article>
        <article className="heroCard">
          <span>Orders completed</span>
          <strong>{totals.orders}</strong>
          <small>Current payroll period</small>
        </article>
        <article className="heroCard">
          <span>Overtime / lateness</span>
          <strong>{totals.overtime}m / {totals.late}m</strong>
          <small>Approved attendance records</small>
        </article>
      </section>

      <section className="panelGrid workforceGrid">
        <article className="panel">
          <div className="panelHeading">
            <div>
              <p className="eyebrow">ONBOARDING</p>
              <h2>Add employee</h2>
            </div>
          </div>
          <form className="employeeForm" onSubmit={submitEmployee}>
            <label><span>Full name</span><input required value={form.full_name} onChange={(e) => setForm({...form, full_name:e.target.value})} /></label>
            <label><span>Employee code</span><input required value={form.employee_code} onChange={(e) => setForm({...form, employee_code:e.target.value})} /></label>
            <label><span>Username</span><input required value={form.username} onChange={(e) => setForm({...form, username:e.target.value})} /></label>
            <label><span>Initial password <small>(blank = generated)</small></span><input type="password" value={form.password} onChange={(e) => setForm({...form, password:e.target.value})} /></label>
            <label><span>Email</span><input type="email" value={form.email} onChange={(e) => setForm({...form, email:e.target.value})} /></label>
            <label><span>Phone</span><input value={form.phone} onChange={(e) => setForm({...form, phone:e.target.value})} /></label>
            <label className="wideField"><span>Address</span><input value={form.address} onChange={(e) => setForm({...form, address:e.target.value})} /></label>
            <label>
              <span>Role</span>
              <select value={form.role} onChange={(e) => setForm({...form, role:e.target.value})}>
                <option>PICKER</option>
                <option>RECEIVER</option>
                <option>INVENTORY</option>
                <option>SUPERVISOR</option>
              </select>
            </label>
            <label><span>Job title</span><input value={form.job_title} onChange={(e) => setForm({...form, job_title:e.target.value})} /></label>
            <label><span>Department</span><input value={form.department} onChange={(e) => setForm({...form, department:e.target.value})} /></label>
            <label><span>Base salary (EGP)</span><input type="number" min="0" step="0.01" value={form.base_salary} onChange={(e) => setForm({...form, base_salary:e.target.value})} /></label>
            <label><span>Overtime / hour (EGP)</span><input type="number" min="0" step="0.01" value={form.overtime_rate} onChange={(e) => setForm({...form, overtime_rate:e.target.value})} /></label>
            <label><span>Late grace (minutes)</span><input type="number" min="0" value={form.grace_minutes} onChange={(e) => setForm({...form, grace_minutes:e.target.value})} /></label>
            <button className="primaryButton wideField" disabled={busy}>Create employee</button>
          </form>
        </article>

        <article className="panel">
          <div className="panelHeading">
            <div>
              <p className="eyebrow">ACCOUNT RECOVERY</p>
              <h2>Password reset requests</h2>
            </div>
            <span className="chip">{resets.length} pending</span>
          </div>
          {resets.length === 0 ? (
            <div className="empty compactEmpty">
              <span>✓</span>
              <div><strong>No pending requests</strong><p>Employees can request a reset from the PDA login screen.</p></div>
            </div>
          ) : (
            <div className="resetList">
              {resets.map((item) => (
                <div className="resetRow" key={item.id}>
                  <div>
                    <strong>{item.full_name ?? item.username}</strong>
                    <small>@{item.username} · {new Date(item.requested_at).toLocaleString()}</small>
                  </div>
                  <button onClick={() => void resolveReset(item)} disabled={busy}>
                    Issue temporary password
                  </button>
                </div>
              ))}
            </div>
          )}
        </article>
      </section>

      <section className="panel employeesPanel">
        <div className="panelHeading">
          <div>
            <p className="eyebrow">TEAM</p>
            <h2>Employee overview</h2>
          </div>
        </div>
        <div className="employeeCards">
          {employees.map((item) => {
            const profile = item.profile;
            const payroll = item.payroll;
            if (!profile) return null;
            return (
              <article className="employeeCard" key={item.user_id}>
                <div className="employeeIdentity">
                  <div>
                    <strong>{profile.full_name}</strong>
                    <span>{profile.job_title} · {profile.department}</span>
                  </div>
                  <span className={item.active ? "employeeStatus active" : "employeeStatus"}>
                    {item.active ? "Active" : "Inactive"}
                  </span>
                </div>
                <div className="employeeMeta">
                  <span>{profile.employee_code}</span>
                  <span>@{item.username}</span>
                  <span>{item.role}</span>
                  {profile.email && <span>{profile.email}</span>}
                  {profile.phone && <span>{profile.phone}</span>}
                </div>
                {payroll && (
                  <>
                    <div className="employeeMetrics">
                      <div><small>Estimated pay</small><strong>{money(payroll.estimated_total_cents, payroll.currency)}</strong></div>
                      <div><small>Orders</small><strong>{payroll.completed_orders}</strong></div>
                      <div><small>Overtime</small><strong>{payroll.overtime_minutes}m</strong></div>
                      <div><small>Late attendance</small><strong>{payroll.late_minutes}m</strong></div>
                      <div><small>Late SLAM</small><strong>{payroll.performance_events.LATE_SLAM ?? 0}</strong></div>
                      <div><small>Late delivery</small><strong>{payroll.performance_events.LATE_DELIVERY ?? 0}</strong></div>
                    </div>
                    <p className="policyNote">{payroll.policy_note}</p>
                  </>
                )}
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
