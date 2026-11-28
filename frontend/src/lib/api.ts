import type { BackendHealth } from "@/types";

const API_BASE_URL = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * Server-side probe of the FastAPI health endpoint, exposed to the browser
 * through /api/health so no backend URL or key ever reaches client code.
 */
export async function fetchBackendHealth(): Promise<BackendHealth> {
  const started = Date.now();
  try {
    const response = await fetch(`${API_BASE_URL}/health`, {
      headers: process.env.SIMILIA_DESKTOP_TOKEN
        ? { "X-Similia-Desktop-Token": process.env.SIMILIA_DESKTOP_TOKEN }
        : undefined,
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (!response.ok) {
      return { backend: "down" };
    }
    const body = await response.json().catch(() => null);
    if (process.env.SIMILIA_DESKTOP_TOKEN && body?.status !== "ok") {
      return { backend: "down" };
    }
    const instanceId = body?.instance_id;
    return {
      backend: "ok",
      latencyMs: Date.now() - started,
      ...(typeof instanceId === "string" ? { instanceId } : {}),
    };
  } catch {
    return { backend: "down" };
  }
}
