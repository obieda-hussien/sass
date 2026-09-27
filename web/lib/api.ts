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
  completed_orders: number;
  performance_events: Record<string, number>;
  policy_note: string;
};

export type Employee = {
  user_id: string;
  username: string;
  role: string;
  active: boolean;
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

async function jsonRequest<T>(
  path: string,
  init: RequestInit = {},
  token?: string,
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(apiUrl(path), {
    ...init,
    headers,
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
  return jsonRequest<{
    access_token: string;
    refresh_token: string;
    username: string;
    role: string;
  }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({
      username,
      password,
      device_id: "WEB-CONTROL-TOWER",
      app_version: "web-0.2.1",
    }),
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
