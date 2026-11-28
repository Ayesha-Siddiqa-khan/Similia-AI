import { NextResponse } from "next/server";

import { fetchBackendHealth } from "@/lib/api";

/** GET /api/health — proxies the FastAPI health check (always HTTP 200). */
export async function GET(): Promise<NextResponse> {
  return NextResponse.json(await fetchBackendHealth(), {
    headers: { "Cache-Control": "no-store" },
  });
}
