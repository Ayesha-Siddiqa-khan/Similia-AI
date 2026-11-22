export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

/** Call the backend through the authenticated same-origin proxy (`/api/backend/*`). */
export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try { response = await fetch(`/api/backend/${path}`, init); }
  catch { throw new ApiError("Backend unreachable. Check your connection and try again.", 0); }
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(typeof body.detail === "string" ? body.detail : "Request could not be completed", response.status);
  return body as T;
}
