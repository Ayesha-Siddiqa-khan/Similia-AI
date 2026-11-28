/** Shared frontend types. */

/** Backend connectivity as shown by the homepage indicator. */
export type BackendStatus = "ok" | "down" | "checking";

/** Shape returned by the local /api/health proxy route. */
export interface BackendHealth {
  backend: "ok" | "down";
  latencyMs?: number;
  instanceId?: string;
}
