export type AuditEvent = {
  id: string;
  actor_user_id: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  field_name: string | null;
  old_value_json: string | null;
  new_value_json: string | null;
  reason: string | null;
  request_id: string | null;
  created_at: string;
};

export type EffectivePermissions = {
  user_id: string;
  role: string;
  permissions: string[];
  role_overrides: Array<{ permission: string; allowed: boolean }>;
  user_overrides: Array<{ permission: string; allowed: boolean }>;
};

export type SystemHealth = {
  version: string;
  database: string;
  telemetry: string;
  outbox: { pending: number; published: number; failed: number };
  otel_exporter_configured: boolean;
  incident_webhook_configured: boolean;
  server_time: string;
};

export type Summary = {
  associates: Record<string, number>;
  tasks: Record<string, number>;
  recoveryRequired: Array<{
    taskId: string;
    orderId: string;
    associateId: string | null;
    reason: string | null;
    version: number;
  }>;
};

const configuredBase = process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "");

export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  if (configuredBase) return `${configuredBase}${normalized}`;
  // On Vercel Services the FastAPI service is mounted at /api.
  return `/api${normalized}`;
}

export async function getSummary(signal?: AbortSignal): Promise<Summary> {
  const response = await fetch(apiUrl("/v1/control-tower/summary"), {
    signal,
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Control tower request failed: ${response.status}`);
  }
  return response.json();
}


export type PayrollPreview = {
  period: string;
  currency: string;
  base_salary_cents: number;
  overtime_minutes: number;
  overtime_pay_cents: number;
  approved_adjustments_cents: number;
  estimated_total_cents: number;
  late_minutes: number;
  early_leave_minutes?: number;
  worked_minutes?: number;
  calculated_attendance_deduction_cents?: number;
  auto_apply_attendance_deductions?: boolean;
  completed_orders: number;
  performance_events: Record<string, number>;
  policy_note: string;
};

export type PromotionRecord = {
  id: string;
  from_role: string;
  to_role: string;
  reason: string;
  old_base_salary_cents: number;
  new_base_salary_cents: number;
  effective_at: string;
  approved_by_user_id: string;
  created_at: string;
};

export type Employee = {
  user_id: string;
  username: string;
  role: string;
  active: boolean;
  must_change_password: boolean;
  deleted_at: string | null;
  profile: {
    employee_code: string;
    full_name: string;
    email: string | null;
    phone: string | null;
    address: string | null;
    job_title: string;
    department: string;
    hire_date: string | null;
    employment_status: string;
    currency: string;
    base_salary_cents: number;
    overtime_rate_cents_per_hour: number;
    scheduled_start_minutes: number | null;
    grace_minutes: number;
    notes: string | null;
  } | null;
  payroll: PayrollPreview | null;
  promotion_history: PromotionRecord[];
  temporary_password?: string | null;
};

export type PasswordResetItem = {
  id: string;
  user_id: string;
  username: string | null;
  full_name: string | null;
  requested_at: string;
  status: string;
};

function browserCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const prefix = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(prefix)) return decodeURIComponent(value.slice(prefix.length));
  }
  return null;
}

async function jsonRequest<T>(
  path: string,
  init: RequestInit = {},
  _session?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const method = (init.method ?? "GET").toUpperCase();
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    const csrf = browserCookie("fo_csrf");
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const response = await fetch(`/web-api${normalized}`, {
    ...init,
    headers,
    credentials: "same-origin",
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail?.message ?? body?.message ?? `Request failed: ${response.status}`;
    throw new Error(message);
  }
  return body as T;
}

export async function managerLogin(username: string, password: string) {
  const response = await fetch("/web-auth/login", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    cache: "no-store",
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body?.detail;
    throw new Error(
      typeof detail === "string"
        ? detail
        : detail?.message ?? body?.message ?? `Login failed: ${response.status}`,
    );
  }
  return body as {
    authenticated: true;
    user_id: string;
    username: string;
    role: string;
  };
}

export async function getWebSession() {
  const response = await fetch("/web-auth/session", {
    method: "GET",
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok) return { authenticated: false as const };
  return response.json() as Promise<{
    authenticated: true;
    user_id: string;
    username: string;
    role: string;
    device_id: string;
  }>;
}

export async function managerLogout() {
  await fetch("/web-auth/logout", {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
  });
}

export async function getEmployees(token: string, period?: string) {
  const suffix = period ? `?period=${encodeURIComponent(period)}` : "";
  return jsonRequest<{ employees: Employee[] }>(
    `/admin/employees${suffix}`,
    {},
    token,
  );
}

export async function createEmployee(
  token: string,
  payload: Record<string, unknown>,
) {
  return jsonRequest<Employee>(
    "/admin/employees",
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}

export async function getPasswordResets(token: string) {
  return jsonRequest<{ requests: PasswordResetItem[] }>(
    "/admin/password-resets",
    {},
    token,
  );
}

export async function issueTemporaryPassword(token: string, resetId: string) {
  return jsonRequest<{
    resolved: boolean;
    temporary_password: string;
    warning: string;
  }>(
    `/admin/password-resets/${resetId}/issue-temporary-password`,
    { method: "POST", body: JSON.stringify({}) },
    token,
  );
}


export async function usernameAvailability(
  session: string,
  username: string,
  excludeUserId?: string,
) {
  const search = new URLSearchParams();
  if (excludeUserId) search.set("exclude_user_id", excludeUserId);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return jsonRequest<{ username: string; available: boolean }>(
    `/admin/usernames/${encodeURIComponent(username)}/availability${suffix}`,
    {},
    session,
  );
}

export async function updateEmployeeAccount(
  session: string,
  userId: string,
  username: string,
) {
  return jsonRequest<{ user_id: string; username: string; sessions_revoked: boolean }>(
    `/admin/employees/${encodeURIComponent(userId)}/account`,
    { method: "PATCH", body: JSON.stringify({ username }) },
    session,
  );
}

export async function setEmployeePin(
  session: string,
  userId: string,
  payload: { password?: string | null; require_change_on_next_login?: boolean },
) {
  return jsonRequest<{
    user_id: string;
    temporary_password: string;
    must_change_password: boolean;
    sessions_revoked: boolean;
    warning: string;
  }>(
    `/admin/employees/${encodeURIComponent(userId)}/set-pin`,
    { method: "POST", body: JSON.stringify(payload) },
    session,
  );
}

export async function deleteEmployee(
  session: string,
  userId: string,
  reason: string,
) {
  return jsonRequest<{
    user_id: string;
    deleted: boolean;
    active: boolean;
    deleted_at: string | null;
  }>(
    `/admin/employees/${encodeURIComponent(userId)}`,
    { method: "DELETE", body: JSON.stringify({ reason }) },
    session,
  );
}


export async function promoteEmployee(
  token: string,
  userId: string,
  payload: {
    to_role: string;
    reason: string;
    new_base_salary_cents?: number | null;
    effective_at?: string | null;
  },
) {
  return jsonRequest<{
    promotion_id: string;
    user_id: string;
    from_role: string;
    to_role: string;
    reason: string;
    old_base_salary_cents: number;
    new_base_salary_cents: number;
    effective_at: string;
    approved_by_user_id: string;
    employee: Employee;
  }>(
    `/admin/employees/${userId}/promote`,
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}


export async function addAttendance(
  token: string,
  userId: string,
  payload: {
    scheduled_start_at: string;
    clock_in_at: string;
    clock_out_at?: string | null;
    overtime_minutes: number;
    status?: string;
    notes?: string | null;
  },
) {
  return jsonRequest<{
    id: string;
    late_minutes: number;
    overtime_minutes: number;
    status: string;
  }>(
    `/admin/employees/${userId}/attendance`,
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}

export async function addPerformanceEvent(
  token: string,
  userId: string,
  payload: {
    event_type: string;
    order_id?: string | null;
    task_id?: string | null;
    minutes: number;
    notes?: string | null;
  },
) {
  return jsonRequest<{ id: string; event_type: string; occurred_at: string }>(
    `/admin/employees/${userId}/performance-events`,
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}

export async function addPayAdjustment(
  token: string,
  userId: string,
  payload: {
    kind: string;
    amount_cents: number;
    reason: string;
    approved: boolean;
  },
) {
  return jsonRequest<{
    id: string;
    kind: string;
    amount_cents: number;
    approved: boolean;
  }>(
    `/admin/employees/${userId}/pay-adjustments`,
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}


export type DispatchWorker = {
  user_id: string;
  username: string;
  full_name: string;
  state: string;
  activity_ref: string | null;
  dispatchable: boolean;
  reasons: string[];
  active_task_id: string | null;
  qualifications: string[];
  required_qualifications: string[];
  device_live: boolean;
  device_last_seen_at: string | null;
  device?: {
    device_id: string;
    battery_percent: number | null;
    connectivity: string | null;
    last_location_id: string | null;
    activity: string | null;
    updated_at: string;
  } | null;
};

export type AvailabilityHold = {
  id: string;
  scope_type: string;
  scope_value: string;
  reason: string;
  notes?: string | null;
  hard_stop: boolean;
  effective: boolean;
  active: boolean;
  starts_at: string;
  expires_at?: string | null;
};

export type OrderSearchResult = {
  order_id: string;
  external_ref: string | null;
  status: string;
  task_id?: string | null;
  picker: { user_id: string; username: string } | null;
  created_at: string;
  pick_started_at: string | null;
  pick_finished_at: string | null;
  sku_count: number;
  requested_units: number;
  picked_units: number;
  shorted_units: number;
  bag_count: number;
  bags: Array<{
    bag_no: number;
    spoo_last4: string;
    spoo_masked: string;
    spoo_code: string;
    closed_at: string;
  }>;
  items: Array<{
    product_id: string;
    asin: string | null;
    title: string;
    requested_qty: number;
    picked_qty: number;
    shorted_qty: number;
  }>;
};

export type PerformanceRow = {
  user_id: string;
  username: string;
  full_name: string;
  orders: number;
  items: number;
  bags: number;
  late_slam: number;
  late_slam_rate: number;
  avg_pick_seconds: number | null;
};

export async function getDispatchWorkers(token: string, taskId?: string) {
  const suffix = taskId ? `?task_id=${encodeURIComponent(taskId)}` : "";
  return jsonRequest<{ workers: DispatchWorker[] }>(
    `/ops/dispatch/workers${suffix}`,
    {},
    token,
  );
}

export async function directAssignTask(
  token: string,
  taskId: string,
  userId: string,
  reason = "MANUAL_DISPATCH",
) {
  return jsonRequest<{ task: Record<string, unknown> }>(
    `/ops/dispatch/tasks/${encodeURIComponent(taskId)}/assign`,
    {
      method: "POST",
      body: JSON.stringify({ user_id: userId, reason }),
    },
    token,
  );
}

export async function getAvailabilityHolds(token: string, siteId = "DEMO") {
  return jsonRequest<{ holds: AvailabilityHold[] }>(
    `/ops/availability/holds?site_id=${encodeURIComponent(siteId)}`,
    {},
    token,
  );
}

export async function createAvailabilityHold(
  token: string,
  payload: {
    site_id?: string;
    scope_type: string;
    scope_value: string;
    reason: string;
    notes?: string | null;
    hard_stop?: boolean;
    starts_at?: string | null;
    expires_at?: string | null;
  },
) {
  return jsonRequest<{
    hold: AvailabilityHold;
    impact: {
      affected_skus: number;
      affected_locations: number;
      affected_available_units: number;
      fully_unavailable_skus: number;
      still_available_elsewhere: number;
    };
  }>(
    "/ops/availability/holds",
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}

export async function resumeAvailabilityHold(token: string, holdId: string) {
  return jsonRequest<{ id: string; active: boolean; ended_at: string }>(
    `/ops/availability/holds/${encodeURIComponent(holdId)}/resume`,
    { method: "POST", body: JSON.stringify({}) },
    token,
  );
}

export async function searchOperationalOrders(
  token: string,
  params: {
    q?: string;
    order_id?: string;
    spoo?: string;
    username?: string;
    from?: string;
    to?: string;
    limit?: number;
  },
) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") search.set(key, String(value));
  });
  return jsonRequest<{ count: number; orders: OrderSearchResult[] }>(
    `/ops/orders/search?${search.toString()}`,
    {},
    token,
  );
}

export async function getOperationalPerformance(
  token: string,
  from?: string,
  to?: string,
) {
  const search = new URLSearchParams();
  if (from) search.set("from", from);
  if (to) search.set("to", to);
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return jsonRequest<{
    from: string;
    to: string;
    rows: PerformanceRow[];
    policy_note: string;
  }>(`/ops/performance${suffix}`, {}, token);
}

export async function getSlottingSuggestions(token: string, days = 30) {
  return jsonRequest<{
    days: number;
    automatic_move: boolean;
    suggestions: Array<{
      product_id: string;
      asin: string | null;
      title: string;
      picked_units: number;
      current_locations: string[];
      current_aisles: number[];
      suggestion: string;
      action_requires_manager_approval: boolean;
    }>;
  }>(`/ops/slotting/suggestions?days=${days}`, {}, token);
}

export async function getShipments(token: string) {
  return jsonRequest<{ shipments: Array<Record<string, any>> }>(
    "/ops/shipments",
    {},
    token,
  );
}


export async function getPayrollPolicy(token: string, userId: string) {
  return jsonRequest<{
    user_id: string;
    late_deduction_cents_per_minute: number;
    early_leave_deduction_cents_per_minute: number;
    auto_apply_attendance_deductions: boolean;
  }>(`/ops/payroll-policy/${encodeURIComponent(userId)}`, {}, token);
}

export async function updatePayrollPolicy(
  token: string,
  userId: string,
  payload: {
    late_deduction_cents_per_minute: number;
    early_leave_deduction_cents_per_minute: number;
    auto_apply_attendance_deductions: boolean;
  },
) {
  return jsonRequest<{
    user_id: string;
    late_deduction_cents_per_minute: number;
    early_leave_deduction_cents_per_minute: number;
    auto_apply_attendance_deductions: boolean;
  }>(
    `/ops/payroll-policy/${encodeURIComponent(userId)}`,
    { method: "PUT", body: JSON.stringify(payload) },
    token,
  );
}


export type ReplenishmentTask = {
  id: string;
  product_id: string;
  asin: string | null;
  title: string;
  source_location_id: string;
  destination_location_id: string;
  qty: number;
  actual_qty: number;
  status: string;
  trigger: string;
  priority: number;
  assigned_user_id: string | null;
  source_available_qty: number;
  destination_on_hand: number;
  created_at: string;
};

export async function getReplenishmentQueue(token: string) {
  return jsonRequest<{ tasks: ReplenishmentTask[] }>(
    "/ops/replenishment/queue",
    {},
    token,
  );
}

export async function generateReplenishment(
  token: string,
  lowStockThreshold = 3,
  targetQty = 12,
) {
  return jsonRequest<{ created: number; tasks: ReplenishmentTask[] }>(
    "/ops/replenishment/generate",
    {
      method: "POST",
      body: JSON.stringify({
        low_stock_threshold: lowStockThreshold,
        target_qty: targetQty,
        max_new_tasks: 100,
      }),
    },
    token,
  );
}

export type ShiftTemplate = {
  id: string;
  site_id: string;
  name: string;
  start_minute: number;
  end_minute: number;
  timezone_name: string;
  break_minutes: number;
  grace_minutes: number;
  active: boolean;
};

export type ShiftAssignment = {
  id: string;
  user_id: string;
  username: string | null;
  shift_date: string;
  template_id: string | null;
  template_name: string | null;
  scheduled_start_at: string;
  scheduled_end_at: string;
  status: string;
  notes: string | null;
};

export async function getShiftTemplates(token: string) {
  return jsonRequest<{ templates: ShiftTemplate[] }>(
    "/ops/shifts/templates",
    {},
    token,
  );
}

export async function createShiftTemplate(
  token: string,
  payload: {
    site_id?: string;
    name: string;
    start_minute: number;
    end_minute: number;
    timezone_name?: string;
    break_minutes: number;
    grace_minutes: number;
  },
) {
  return jsonRequest<ShiftTemplate>(
    "/ops/shifts/templates",
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}

export async function getRoster(
  token: string,
  from: string,
  to: string,
  userId?: string,
) {
  const q = new URLSearchParams({ from, to });
  if (userId) q.set("user_id", userId);
  return jsonRequest<{ assignments: ShiftAssignment[] }>(
    `/ops/shifts/roster?${q.toString()}`,
    {},
    token,
  );
}

export async function assignShift(
  token: string,
  payload: {
    user_id: string;
    shift_template_id: string;
    shift_date: string;
    notes?: string | null;
  },
) {
  return jsonRequest<ShiftAssignment>(
    "/ops/shifts/assignments",
    { method: "POST", body: JSON.stringify(payload) },
    token,
  );
}


export async function getSystemHealth(session: string) {
  return jsonRequest<SystemHealth>("/admin/system/health", {}, session);
}

export async function getAuditEvents(
  session: string,
  params: { entity_type?: string; entity_id?: string; limit?: number } = {},
) {
  const search = new URLSearchParams();
  if (params.entity_type) search.set("entity_type", params.entity_type);
  if (params.entity_id) search.set("entity_id", params.entity_id);
  search.set("limit", String(params.limit ?? 100));
  return jsonRequest<{ events: AuditEvent[] }>(
    `/ops/audit?${search.toString()}`,
    {},
    session,
  );
}

export async function getMyPermissions(session: string) {
  return jsonRequest<EffectivePermissions>("/ops/permissions/me", {}, session);
}

export async function setRolePermission(
  session: string,
  role: string,
  permission: string,
  allowed: boolean,
) {
  return jsonRequest<{ role: string; permission: string; allowed: boolean }>(
    `/ops/permissions/roles/${encodeURIComponent(role)}`,
    {
      method: "PUT",
      body: JSON.stringify({ permission, allowed }),
    },
    session,
  );
}

export async function setUserPermission(
  session: string,
  userId: string,
  permission: string,
  allowed: boolean,
) {
  return jsonRequest<{ user_id: string; permission: string; allowed: boolean }>(
    `/ops/permissions/users/${encodeURIComponent(userId)}`,
    {
      method: "PUT",
      body: JSON.stringify({ permission, allowed }),
    },
    session,
  );
}
