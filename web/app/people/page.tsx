"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  addAttendance,
  addPayAdjustment,
  addPerformanceEvent,
  createEmployee,
  createShiftTemplate,
  assignShift,
  getEmployees,
  getPasswordResets,
  getRoster,
  getShiftTemplates,
  issueTemporaryPassword,
  managerLogin,
  getWebSession,
  managerLogout,
  promoteEmployee,
  type Employee,
  type PasswordResetItem,
  type ShiftAssignment,
  type ShiftTemplate,
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

const promotionRanks = [
  "PICKER",
  "SENIOR_PICKER",
  "QUALITY",
  "QUALITY_LEADER",
  "TEAM_LEADER",
  "SUPERVISOR",
] as const;

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

function generateSixDigitPin() {
  const value = new Uint32Array(1);
  window.crypto.getRandomValues(value);
  return String(100000 + (value[0] % 900000));
}

function timeFromMinutes(value: number) {
  const hours = Math.floor(value / 60) % 24;
  const minutes = value % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function minutesFromTime(value: string) {
  const [hours, minutes] = value.split(":").map(Number);
  return hours * 60 + minutes;
}

function money(cents: number, currency = "EGP") {
  return new Intl.NumberFormat("en-EG", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(cents / 100);
}

export default function PeoplePage() {
  const [token, setToken] = useState("");
  const [authChecking, setAuthChecking] = useState(true);
  const [loginUser, setLoginUser] = useState("supervisor");
  const [loginPassword, setLoginPassword] = useState("");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [resets, setResets] = useState<PasswordResetItem[]>([]);
  const [shiftTemplates, setShiftTemplates] = useState<ShiftTemplate[]>([]);
  const [roster, setRoster] = useState<ShiftAssignment[]>([]);
  const [form, setForm] = useState<CreateForm>(emptyForm);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const [attendanceForm, setAttendanceForm] = useState({
    scheduled_start_at: "",
    clock_in_at: "",
    clock_out_at: "",
    overtime_minutes: "0",
    notes: "",
  });
  const [performanceForm, setPerformanceForm] = useState({
    event_type: "LATE_SLAM",
    minutes: "0",
    notes: "",
  });
  const [adjustmentForm, setAdjustmentForm] = useState({
    kind: "MANUAL_ADJUSTMENT",
    amount: "",
    reason: "",
  });
  const [promotionForm, setPromotionForm] = useState({
    to_role: "SENIOR_PICKER",
    new_base_salary: "",
    reason: "",
  });
  const [shiftTemplateForm, setShiftTemplateForm] = useState({
    name: "Middle",
    start: "14:00",
    end: "23:00",
    break_minutes: "30",
    grace_minutes: "10",
  });
  const [shiftAssignmentForm, setShiftAssignmentForm] = useState({
    user_id: "",
    shift_template_id: "",
    shift_date: new Date().toISOString().slice(0, 10),
  });

  useEffect(() => {
    void getWebSession()
      .then((session) => {
        if (
          session.authenticated &&
          ["SUPERVISOR", "ADMIN"].includes(session.role.toUpperCase())
        ) {
          setToken("session");
        }
      })
      .finally(() => setAuthChecking(false));
  }, []);

  async function refresh(activeToken = token) {
    if (!activeToken) return;
    try {
      const today = new Date();
      const from = today.toISOString().slice(0, 10);
      const end = new Date(today);
      end.setDate(end.getDate() + 7);
      const to = end.toISOString().slice(0, 10);
      const [people, resetData, templateData, rosterData] = await Promise.all([
        getEmployees(activeToken),
        getPasswordResets(activeToken),
        getShiftTemplates(activeToken),
        getRoster(activeToken, from, to),
      ]);
      setEmployees(people.employees);
      setResets(resetData.requests);
      setShiftTemplates(templateData.templates);
      setRoster(rosterData.assignments);
      setShiftAssignmentForm((current) => ({
        ...current,
        user_id: current.user_id || people.employees[0]?.user_id || "",
        shift_template_id: current.shift_template_id || templateData.templates[0]?.id || "",
      }));
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
      setToken("session");
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
          ? `Employee created. Temporary PIN: ${created.temporary_password}`
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
        `Temporary PIN for ${item.username ?? item.full_name ?? "employee"}: ${result.temporary_password}`,
      );
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not reset password");
    } finally {
      setBusy(false);
    }
  }

  const selectedEmployee = useMemo(
    () => employees.find((item) => item.user_id === selectedId) ?? null,
    [employees, selectedId],
  );

  const promotionTargets = useMemo(() => {
    if (!selectedEmployee) return [...promotionRanks];
    const currentIndex = promotionRanks.indexOf(
      selectedEmployee.role as (typeof promotionRanks)[number],
    );
    return currentIndex < 0 ? [...promotionRanks] : promotionRanks.slice(currentIndex + 1);
  }, [selectedEmployee]);

  useEffect(() => {
    if (!selectedEmployee || promotionTargets.length === 0) return;
    if (!promotionTargets.includes(promotionForm.to_role as (typeof promotionRanks)[number])) {
      setPromotionForm((current) => ({...current, to_role: promotionTargets[0]}));
    }
  }, [selectedEmployee, promotionTargets, promotionForm.to_role]);

  async function submitAttendance(event: FormEvent) {
    event.preventDefault();
    if (!token || !selectedEmployee) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await addAttendance(token, selectedEmployee.user_id, {
        scheduled_start_at: new Date(attendanceForm.scheduled_start_at).toISOString(),
        clock_in_at: new Date(attendanceForm.clock_in_at).toISOString(),
        clock_out_at: attendanceForm.clock_out_at
          ? new Date(attendanceForm.clock_out_at).toISOString()
          : null,
        overtime_minutes: Number(attendanceForm.overtime_minutes || "0"),
        status: "APPROVED",
        notes: attendanceForm.notes || null,
      });
      setNotice(
        `Attendance saved · late ${result.late_minutes}m · overtime ${result.overtime_minutes}m`,
      );
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not save attendance");
    } finally {
      setBusy(false);
    }
  }

  async function submitPerformance(event: FormEvent) {
    event.preventDefault();
    if (!token || !selectedEmployee) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await addPerformanceEvent(token, selectedEmployee.user_id, {
        event_type: performanceForm.event_type,
        minutes: Number(performanceForm.minutes || "0"),
        notes: performanceForm.notes || null,
      });
      setNotice("Operational event recorded for supervisor review.");
      setPerformanceForm({...performanceForm, minutes: "0", notes: ""});
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not record event");
    } finally {
      setBusy(false);
    }
  }

  async function submitPromotion(event: FormEvent) {
    event.preventDefault();
    if (!token || !selectedEmployee?.profile) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await promoteEmployee(token, selectedEmployee.user_id, {
        to_role: promotionForm.to_role,
        reason: promotionForm.reason,
        new_base_salary_cents: promotionForm.new_base_salary
          ? Math.round(Number(promotionForm.new_base_salary) * 100)
          : null,
      });
      setNotice(
        `Promotion approved: ${result.from_role} → ${result.to_role}` +
          (result.new_base_salary_cents !== result.old_base_salary_cents
            ? ` · salary ${money(result.old_base_salary_cents)} → ${money(result.new_base_salary_cents)}`
            : ""),
      );
      setPromotionForm({
        to_role: "SENIOR_PICKER",
        new_base_salary: "",
        reason: "",
      });
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not approve promotion");
    } finally {
      setBusy(false);
    }
  }

  async function submitAdjustment(event: FormEvent) {
    event.preventDefault();
    if (!token || !selectedEmployee) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await addPayAdjustment(token, selectedEmployee.user_id, {
        kind: adjustmentForm.kind,
        amount_cents: Math.round(Number(adjustmentForm.amount || "0") * 100),
        reason: adjustmentForm.reason,
        approved: true,
      });
      setNotice("Approved payroll adjustment added.");
      setAdjustmentForm({...adjustmentForm, amount: "", reason: ""});
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not add pay adjustment");
    } finally {
      setBusy(false);
    }
  }

  async function submitShiftTemplate(event: FormEvent) {
    event.preventDefault();
    if (!token) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await createShiftTemplate(token, {
        site_id: "DEMO",
        name: shiftTemplateForm.name,
        start_minute: minutesFromTime(shiftTemplateForm.start),
        end_minute: minutesFromTime(shiftTemplateForm.end),
        timezone_name: "Africa/Cairo",
        break_minutes: Number(shiftTemplateForm.break_minutes || "0"),
        grace_minutes: Number(shiftTemplateForm.grace_minutes || "0"),
      });
      setNotice(`Shift template created: ${created.name}`);
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not create shift template");
    } finally {
      setBusy(false);
    }
  }

  async function submitShiftAssignment(event: FormEvent) {
    event.preventDefault();
    if (!token || !shiftAssignmentForm.user_id || !shiftAssignmentForm.shift_template_id) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await assignShift(token, {
        user_id: shiftAssignmentForm.user_id,
        shift_template_id: shiftAssignmentForm.shift_template_id,
        shift_date: shiftAssignmentForm.shift_date,
      });
      setNotice(`Shift assigned for ${created.shift_date}`);
      await refresh(token);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not assign shift");
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

  if (authChecking) {
    return <main className="shell peopleShell"><section className="panel authPanel">Checking secure session…</section></main>;
  }

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
              void managerLogout();
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

      <nav className="sectionJumpNav" aria-label="People sections">
        <a href="#onboarding">Add employee</a>
        <a href="#schedule">Shift schedule</a>
        <a href="#team">Team</a>
        <a href="#payroll">Attendance & payroll</a>
      </nav>

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

      <section id="onboarding" className="panelGrid workforceGrid">
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
            <label className="pinField">
              <span>Initial PIN <small>(6–10 digits; blank = random 6 digits)</small></span>
              <div className="inlineFieldAction">
                <input
                  type="password"
                  inputMode="numeric"
                  pattern="[0-9]{6,10}"
                  minLength={6}
                  maxLength={10}
                  value={form.password}
                  onChange={(e) => setForm({...form, password:e.target.value.replace(/\D/g, "").slice(0, 10)})}
                />
                <button type="button" className="miniAction" onClick={() => setForm({...form, password:generateSixDigitPin()})}>
                  Generate 6-digit
                </button>
              </div>
            </label>
            <label><span>Email</span><input type="email" value={form.email} onChange={(e) => setForm({...form, email:e.target.value})} /></label>
            <label><span>Phone</span><input value={form.phone} onChange={(e) => setForm({...form, phone:e.target.value})} /></label>
            <label className="wideField"><span>Address</span><input value={form.address} onChange={(e) => setForm({...form, address:e.target.value})} /></label>
            <label>
              <span>Role</span>
              <select value={form.role} onChange={(e) => setForm({...form, role:e.target.value})}>
                {promotionRanks.map((role) => <option key={role}>{role}</option>)}
                <option>RECEIVER</option>
                <option>INVENTORY</option>
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
                    Issue temporary PIN
                  </button>
                </div>
              ))}
            </div>
          )}
        </article>
      </section>

      <section id="schedule" className="panel opsSection">
        <div className="panelHeading">
          <div>
            <p className="eyebrow">SHIFT SCHEDULE</p>
            <h2>Templates & next 7 days</h2>
          </div>
          <span className="chip">{roster.length} assignments</span>
        </div>
        <p className="sectionHelp">
          Create a reusable shift once, then assign employees by date. Clock-in/out can use the scheduled window automatically.
        </p>
        <div className="managerForms">
          <form className="managerForm" onSubmit={submitShiftTemplate}>
            <h3>Create shift template</h3>
            <label><span>Name</span><input required value={shiftTemplateForm.name} onChange={(e) => setShiftTemplateForm({...shiftTemplateForm, name:e.target.value})} /></label>
            <label><span>Start</span><input type="time" required value={shiftTemplateForm.start} onChange={(e) => setShiftTemplateForm({...shiftTemplateForm, start:e.target.value})} /></label>
            <label><span>End</span><input type="time" required value={shiftTemplateForm.end} onChange={(e) => setShiftTemplateForm({...shiftTemplateForm, end:e.target.value})} /></label>
            <label><span>Break minutes</span><input type="number" min="0" value={shiftTemplateForm.break_minutes} onChange={(e) => setShiftTemplateForm({...shiftTemplateForm, break_minutes:e.target.value})} /></label>
            <label><span>Grace minutes</span><input type="number" min="0" value={shiftTemplateForm.grace_minutes} onChange={(e) => setShiftTemplateForm({...shiftTemplateForm, grace_minutes:e.target.value})} /></label>
            <button className="primaryButton" disabled={busy}>Save template</button>
          </form>

          <form className="managerForm" onSubmit={submitShiftAssignment}>
            <h3>Assign employee</h3>
            <label><span>Employee</span><select value={shiftAssignmentForm.user_id} onChange={(e) => setShiftAssignmentForm({...shiftAssignmentForm, user_id:e.target.value})}>{employees.map((employee) => <option key={employee.user_id} value={employee.user_id}>{employee.profile?.full_name ?? employee.username}</option>)}</select></label>
            <label><span>Shift</span><select value={shiftAssignmentForm.shift_template_id} onChange={(e) => setShiftAssignmentForm({...shiftAssignmentForm, shift_template_id:e.target.value})}>{shiftTemplates.map((template) => <option key={template.id} value={template.id}>{template.name} · {timeFromMinutes(template.start_minute)}–{timeFromMinutes(template.end_minute)}</option>)}</select></label>
            <label><span>Date</span><input type="date" required value={shiftAssignmentForm.shift_date} onChange={(e) => setShiftAssignmentForm({...shiftAssignmentForm, shift_date:e.target.value})} /></label>
            <button className="primaryButton" disabled={busy || shiftTemplates.length === 0 || employees.length === 0}>Assign shift</button>
          </form>
        </div>

        <div className="rosterGrid" style={{marginTop: 12}}>
          {roster.length === 0 ? (
            <div className="empty compactEmpty"><span>⌚</span><div><strong>No scheduled shifts in the next 7 days</strong><p>Create a template, then assign an employee.</p></div></div>
          ) : roster.map((item) => (
            <div className="rosterRow" key={item.id}>
              <div><strong>{item.username ?? item.user_id}</strong><small>{item.template_name ?? "Custom shift"} · {item.shift_date}</small></div>
              <div><small>Start</small><strong>{new Date(item.scheduled_start_at).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})}</strong></div>
              <div><small>End</small><strong>{new Date(item.scheduled_end_at).toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"})}</strong></div>
              <div><small>Status</small><strong>{item.status}</strong></div>
            </div>
          ))}
        </div>
      </section>

      <section id="team" className="panel employeesPanel">
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
                  <div className="employeeCardActions">
                    <button
                      className="miniAction"
                      onClick={() => setSelectedId(item.user_id)}
                    >
                      Manage
                    </button>
                    <span className={item.active ? "employeeStatus active" : "employeeStatus"}>
                      {item.active ? "Active" : "Inactive"}
                    </span>
                  </div>
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

      {selectedEmployee?.profile && (
        <section id="payroll" className="panel managerPanel">
          <div className="panelHeading">
            <div>
              <p className="eyebrow">SUPERVISOR ACTIONS</p>
              <h2>{selectedEmployee.profile.full_name}</h2>
            </div>
            <button className="miniAction" onClick={() => setSelectedId("")}>Close</button>
          </div>

          <div className="managerForms">
            <form className="managerForm" onSubmit={submitAttendance}>
              <h3>Attendance & overtime</h3>
              <label><span>Scheduled start</span><input type="datetime-local" required value={attendanceForm.scheduled_start_at} onChange={(e) => setAttendanceForm({...attendanceForm, scheduled_start_at:e.target.value})} /></label>
              <label><span>Clock in</span><input type="datetime-local" required value={attendanceForm.clock_in_at} onChange={(e) => setAttendanceForm({...attendanceForm, clock_in_at:e.target.value})} /></label>
              <label><span>Clock out</span><input type="datetime-local" value={attendanceForm.clock_out_at} onChange={(e) => setAttendanceForm({...attendanceForm, clock_out_at:e.target.value})} /></label>
              <label><span>Approved overtime minutes</span><input type="number" min="0" value={attendanceForm.overtime_minutes} onChange={(e) => setAttendanceForm({...attendanceForm, overtime_minutes:e.target.value})} /></label>
              <label><span>Notes</span><input value={attendanceForm.notes} onChange={(e) => setAttendanceForm({...attendanceForm, notes:e.target.value})} /></label>
              <button className="primaryButton" disabled={busy}>Save attendance</button>
            </form>

            <form className="managerForm" onSubmit={submitPerformance}>
              <h3>Operational event</h3>
              <label>
                <span>Type</span>
                <select value={performanceForm.event_type} onChange={(e) => setPerformanceForm({...performanceForm, event_type:e.target.value})}>
                  <option value="LATE_SLAM">Late SLAM</option>
                  <option value="LATE_DELIVERY">Late delivery</option>
                  <option value="ORDER_EXCEPTION">Order exception</option>
                  <option value="SYSTEM_DELAY">System delay</option>
                  <option value="NETWORK_DELAY">Network delay</option>
                </select>
              </label>
              <label><span>Minutes</span><input type="number" min="0" value={performanceForm.minutes} onChange={(e) => setPerformanceForm({...performanceForm, minutes:e.target.value})} /></label>
              <label><span>Notes</span><input value={performanceForm.notes} onChange={(e) => setPerformanceForm({...performanceForm, notes:e.target.value})} /></label>
              <button className="primaryButton" disabled={busy}>Record event</button>
              <p className="policyNote">Operational events are evidence for human review; they do not automatically change pay.</p>
            </form>

            <form className="managerForm" onSubmit={submitPromotion}>
              <h3>Promotion & rank</h3>
              <p className="policyNote">
                Ladder: Picker → Senior Picker → Quality → Quality Leader → Team Leader → Supervisor.
                Promotions are never automatic; this action records who approved it, why, when, and any salary change.
              </p>
              <label>
                <span>Promote to</span>
                <select
                  value={promotionForm.to_role}
                  onChange={(e) => setPromotionForm({...promotionForm, to_role:e.target.value})}
                >
                  {promotionTargets.map((role) => (
                    <option key={role} value={role}>{role.replaceAll("_", " ")}</option>
                  ))}
                </select>
              </label>
              <label>
                <span>New base salary (EGP) <small>(blank = keep current)</small></span>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={promotionForm.new_base_salary}
                  onChange={(e) => setPromotionForm({...promotionForm, new_base_salary:e.target.value})}
                />
              </label>
              <label>
                <span>Promotion reason</span>
                <input
                  required
                  value={promotionForm.reason}
                  onChange={(e) => setPromotionForm({...promotionForm, reason:e.target.value})}
                  placeholder="Performance, quality ownership, leadership readiness…"
                />
              </label>
              <button className="primaryButton" disabled={busy || promotionTargets.length === 0}>
                {promotionTargets.length === 0 ? "Highest warehouse rank" : "Approve promotion"}
              </button>
              {selectedEmployee.promotion_history.length > 0 && (
                <div className="promotionHistory">
                  <strong>Promotion history</strong>
                  {selectedEmployee.promotion_history.slice(0, 6).map((promotion) => (
                    <small key={promotion.id}>
                      {promotion.from_role.replaceAll("_", " ")} → {promotion.to_role.replaceAll("_", " ")}
                      {" · "}{new Date(promotion.effective_at).toLocaleDateString()}
                      {" · "}{promotion.reason}
                    </small>
                  ))}
                </div>
              )}
            </form>

            <form className="managerForm" onSubmit={submitAdjustment}>
              <h3>Approved pay adjustment</h3>
              <label>
                <span>Kind</span>
                <select value={adjustmentForm.kind} onChange={(e) => setAdjustmentForm({...adjustmentForm, kind:e.target.value})}>
                  <option value="BONUS">Bonus</option>
                  <option value="ALLOWANCE">Allowance</option>
                  <option value="MANUAL_ADJUSTMENT">Manual adjustment</option>
                  <option value="DEDUCTION">Deduction</option>
                </select>
              </label>
              <label><span>Amount (EGP; negative for deduction)</span><input type="number" step="0.01" required value={adjustmentForm.amount} onChange={(e) => setAdjustmentForm({...adjustmentForm, amount:e.target.value})} /></label>
              <label><span>Reason</span><input required value={adjustmentForm.reason} onChange={(e) => setAdjustmentForm({...adjustmentForm, reason:e.target.value})} /></label>
              <button className="primaryButton" disabled={busy}>Approve adjustment</button>
              <p className="policyNote">This is the only place operational issues can affect payroll, and it requires an explicit supervisor action with a reason.</p>
            </form>
          </div>
        </section>
      )}
    </main>
  );
}
