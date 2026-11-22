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
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (!response.ok) {
      return { backend: "down" };
    }
    return { backend: "ok", latencyMs: Date.now() - started };
  } catch {
    return { backend: "down" };
  }
}
