import { NextResponse } from "next/server";
import { getGraphQLClient } from "@/lib/graphql/client";
import { createClient } from "@/lib/supabase/server";
import { isOperator, isPractitioner, sameOrigin } from "@/lib/auth";

const base = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
type Context = { params: Promise<{ path: string[] }> };
const headers = { "Cache-Control": "private, no-store" };
const MAX_JSON_BYTES = 1024 * 1024;

const uuid = "[a-f0-9-]{36}";
// Knowledge-base endpoints need an operator; patient/case endpoints need a practitioner.
const operatorRoutes: Record<string, RegExp> = {
  GET: new RegExp(`^(books|monitor/snapshot|monitor/chunks/[a-f0-9]{64}|ingestion-jobs/${uuid}|ingestion-jobs/${uuid}/events|ingestion/overview|books/${uuid}/(ingestion|chunks|text)|graphql)$`),
  POST: new RegExp(`^(books|search|books/${uuid}/(prepare|ingest)|ingestion-jobs/${uuid}/pause)$`),
};
const practitionerRoutes: Record<string, RegExp> = {
  GET: new RegExp(`^(patients|cases|settings/ai|patients/${uuid}|cases/${uuid}|cases/${uuid}/(analysis|analyses)|patients/${uuid}/(consents|history|export))$`),
  POST: new RegExp(`^(patients|cases|settings/ai/(activate|deactivate)|cases/${uuid}/(analyze|review|questions|reopen)|patients/${uuid}/consent(/withdraw)?)$`),
  PATCH: new RegExp(`^(patients|cases)/${uuid}$`),
  PUT: new RegExp(`^(cases/${uuid}/symptoms|settings/ai)$`),
  DELETE: new RegExp(`^(settings/ai|patients/${uuid})$`),
};

const operatorMessages: Record<number, string> = { 401: "Session could not be verified", 403: "Operator access denied", 404: "Record unavailable", 409: "This book is already registered or has an incompatible frozen plan", 413: "Upload exceeds 50 MB", 422: "The backend rejected the supplied fields", 429: "Embedding access is paused pending provider quota verification" };
const practitionerMessages: Record<number, string> = { 401: "Session could not be verified", 403: "Practitioner access denied", 404: "Record not found", 409: "No active patient consent is on record for this case", 422: "One of the boxes is too long or invalid. Shorten the longest answer and try again", 428: "Add your own AI key in AI Settings to use this feature", 429: "Analysis is paused while the embedding provider quota is verified", 503: "A required service is not configured or unavailable. Check the backend AI key and model settings.", 502: "The analysis service failed. Try again later." };

async function handle(request: Request, context: Context) {
  const path = (await context.params).path.join("/");
  const scope = operatorRoutes[request.method]?.test(path) ? "operator" : practitionerRoutes[request.method]?.test(path) ? "practitioner" : null;
  if (!scope) return NextResponse.json({ detail: "Operation unavailable" }, { status: 404, headers });
  if (request.method !== "GET" && !sameOrigin(request)) return NextResponse.json({ detail: "Invalid request origin" }, { status: 403, headers });
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) {
    return NextResponse.json({ detail: "Authentication is not configured" }, { status: 503, headers });
  }
  try {
    const supabase = await createClient();
    const { data: { user }, error } = await supabase.auth.getUser();
    if (error || !user) return NextResponse.json({ detail: "Sign in to continue" }, { status: 401, headers });
    if (scope === "operator" ? !isOperator(user.app_metadata) : !isPractitioner(user.app_metadata)) {
      return NextResponse.json({ detail: scope === "operator" ? "A Similia operator role is required" : "A Similia practitioner role is required" }, { status: 403, headers });
    }
    const { data: { session } } = await supabase.auth.getSession();
    if (!session) return NextResponse.json({ detail: "Session expired" }, { status: 401, headers });
    if (path === "graphql") {
      return NextResponse.json(await getGraphQLClient().request<{ health: string }>("query ServiceHealth { health }"), { headers });
    }
    const init: RequestInit = { method: request.method, headers: { Authorization: `Bearer ${session.access_token}` }, signal: AbortSignal.timeout(scope === "practitioner" && path.endsWith("/analyze") ? 120_000 : path.endsWith("/prepare") ? 120_000 : scope === "practitioner" && path.endsWith("/questions") ? 60_000 : 30_000), cache: "no-store" };
    if (request.method !== "GET") {
      if (Number(request.headers.get("content-length") ?? 0) > 51 * 1024 * 1024) return NextResponse.json({ detail: "Upload exceeds 50 MB" }, { status: 413, headers });
      if (path === "books") {
        const form = await request.formData();
        const file = form.get("file");
        if (!(file instanceof File) || !file.name.toLowerCase().endsWith(".pdf") || file.size === 0 || file.size > 50 * 1024 * 1024) return NextResponse.json({ detail: "Select a PDF between 1 byte and 50 MB" }, { status: 422, headers });
        init.body = form;
      } else {
        const text = await request.text();
        if (text.length > MAX_JSON_BYTES) return NextResponse.json({ detail: "Request too large" }, { status: 413, headers });
        if (text) init.body = text;
        init.headers = { ...init.headers, "Content-Type": "application/json" };
      }
    }
    const response = await fetch(`${base}/api/${path}${new URL(request.url).search}`, init);
    if (!response.ok) {
      // Key-management and missing-key errors carry safe, backend-written messages (never the key itself).
      // These backend messages name the field or rule that failed and never echo user text.
      if (path.startsWith("settings/ai") || [409, 422, 428, 429].includes(response.status)) {
        const detail = (await response.json().catch(() => ({}))).detail;
        if (typeof detail === "string" && detail.length < 300) return NextResponse.json({ detail }, { status: response.status >= 500 && response.status !== 502 ? 503 : response.status, headers });
      }
      const messages = scope === "operator" ? operatorMessages : practitionerMessages;
      return NextResponse.json({ detail: messages[response.status] ?? "Backend service unavailable. Try again later." }, { status: response.status >= 500 && response.status !== 502 ? 503 : response.status, headers });
    }
    if (response.status === 204) return new NextResponse(null, { status: 204, headers });
    return NextResponse.json(await response.json(), { status: response.status, headers });
  } catch {
    return NextResponse.json({ detail: "Service unavailable. Check the backend connection and authentication configuration." }, { status: 503, headers });
  }
}

export const GET = handle;
export const POST = handle;
export const PATCH = handle;
export const PUT = handle;
export const DELETE = handle;
