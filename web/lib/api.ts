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
