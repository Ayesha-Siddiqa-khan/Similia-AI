import { NextResponse } from "next/server";
import { getGraphQLClient } from "@/lib/graphql/client";
import { createClient } from "@/lib/supabase/server";
import { isOperator, isPractitioner, sameOrigin } from "@/lib/auth";

const base = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
// Set by the desktop launcher. The backend rejects /api and /graphql calls
// without it, so another local process cannot drive the clinical API.
const desktopToken = process.env.SIMILIA_DESKTOP_TOKEN ?? "";
type Context = { params: Promise<{ path: string[] }> };
const headers = { "Cache-Control": "private, no-store" };
const MAX_JSON_BYTES = 1024 * 1024;
const MAX_PHOTO_BODY = 8 * 1024 * 1024 + 16 * 1024;
// Include cold worker startup, model loading and inference in the proxy budget.
const speechTimeouts: Partial<Record<string, number>> = {
  "speech/validate": 190_000,
  "speech/load": 250_000,
  "speech/transcribe": 550_000,
};
const analysisProviderErrors = new Set([
  "The AI provider rejected the analysis. Check your key, model and billing in AI Settings.",
  "Claude rejected the analysis because of a billing issue. Check billing and available credits in the Anthropic Console, then try again.",
  "The selected AI provider rejected the analysis because of a billing issue. Check billing and available credits with that provider, then try again.",
  "The AI provider reached its rate or quota limit. Check the limits for your selected model, then try again.",
  "The selected model is unavailable to this API key. Choose another model in AI Settings.",
  "The AI provider rejected the request for this model. Choose another chat model in AI Settings.",
  "The AI provider blocked generation for this account. Check API access and free-tier availability with your provider.",
  "The AI provider returned an incomplete response. Try again or choose another chat model in AI Settings.",
  "The AI provider did not respond. Try again later.",
  "The connection to the AI provider failed or timed out. Try again later.",
  "The AI provider returned HTTP 503 and is temporarily unavailable.",
  "The source library could not be searched. Try again later.",
  "Analysis failed while preparing the search queries. Try again later.",
  "Analysis failed while interpreting the retrieved sources. Try again later.",
]);

const uuid = "[a-f0-9-]{36}";
const clinicalRoot = `cases/${uuid}`;
const clinicalRoutes: Record<string, RegExp> = {
  GET: new RegExp(`^${clinicalRoot}/(workflow(/reports/${uuid}/file)?|photos(/${uuid}/(thumb|full))?)$`),
  POST: new RegExp(`^${clinicalRoot}/(workflow/(research|assessment|final/(review|sign)|reports/${uuid}/urdu)|photos(/observe)?)$`),
  PUT: new RegExp(`^${clinicalRoot}/photos/consent$`),
  DELETE: new RegExp(`^${clinicalRoot}/photos/${uuid}$`),
};
// Knowledge-base endpoints need an operator; patient/case endpoints need a practitioner.
const operatorRoutes: Record<string, RegExp> = {
  GET: new RegExp(`^(books|monitor/snapshot|monitor/chunks/[a-f0-9]{64}|ingestion-jobs/${uuid}|ingestion-jobs/${uuid}/events|ingestion/overview|ingestion/books/list\\.pdf|books/${uuid}/(ingestion|chunks|text)|graphql)$`),
  POST: new RegExp(`^(books|search|books/${uuid}/(prepare|ingest)|ingestion-jobs/${uuid}/pause|ingestion/auto|ingestion/auto/stop)$`),
};
const practitionerRoutes: Record<string, RegExp> = {
  GET: new RegExp(`^(patients|cases|settings/ai|speech/settings|patients/${uuid}|cases/${uuid}|cases/${uuid}/(analysis|analyses|review|prescription/file)|patients/${uuid}/(consents|history|export))$`),
  POST: new RegExp(`^(patients|cases|settings/ai/(activate|deactivate|models|diagnostics)|speech/(settings|validate|load|unload|transcribe)|cases/${uuid}/(analyze|review|questions|reopen|report/(urdu|file))|patients/${uuid}/consent(/withdraw)?)$`),
  PATCH: new RegExp(`^(patients|cases)/${uuid}$`),
  PUT: new RegExp(`^(cases/${uuid}/symptoms|settings/ai(/analysis-limit)?|speech/settings)$`),
  DELETE: new RegExp(`^(settings/ai|patients/${uuid})$`),
};

const operatorMessages: Record<number, string> = { 401: "Session could not be verified", 403: "Operator access denied", 404: "Record unavailable", 409: "This book is already registered or has an incompatible frozen plan", 413: "Upload exceeds 50 MB", 422: "The backend rejected the supplied fields", 429: "Embedding access is paused pending provider quota verification" };
const practitionerMessages: Record<number, string> = { 401: "Session could not be verified", 403: "Practitioner access denied", 404: "Record not found", 409: "No active patient consent is on record for this case", 422: "One of the boxes is too long or invalid. Shorten the longest answer and try again", 428: "Add your own AI key in AI Settings to use this feature", 429: "Analysis is paused while the embedding provider quota is verified", 503: "A required service is not configured or unavailable. Check the backend AI key and model settings.", 502: "The analysis service failed. Try again later." };

async function handle(request: Request, context: Context) {
  const path = (await context.params).path.join("/");
  const clinical = clinicalRoutes[request.method]?.test(path);
  const photoUpload = clinical && request.method === "POST" && path.endsWith("/photos");
  const scope = operatorRoutes[request.method]?.test(path) ? "operator" : clinical || practitionerRoutes[request.method]?.test(path) ? "practitioner" : null;
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
    const timeout = speechTimeouts[path] ?? (
      clinical && request.method === "POST" ? 240_000 :
        path === "books" && request.method === "POST" ? 180_000 :
          scope === "practitioner" && (path.endsWith("/analyze") || path === "settings/ai/diagnostics") ? 120_000 :
            path.endsWith("/prepare") ? 120_000 :
              scope === "practitioner" && (path.endsWith("/questions") || path.endsWith("/report/urdu")) ? 60_000 : 30_000
    );
    const init: RequestInit = { method: request.method, headers: { Authorization: `Bearer ${session.access_token}`, ...(desktopToken ? { "X-Similia-Desktop-Token": desktopToken } : {}) }, signal: AbortSignal.timeout(timeout), cache: "no-store" };
    if (request.method !== "GET") {
      if (Number(request.headers.get("content-length") ?? 0) > 51 * 1024 * 1024) return NextResponse.json({ detail: "Upload exceeds 50 MB" }, { status: 413, headers });
      if (photoUpload) {
        if (Number(request.headers.get("content-length") ?? 0) > MAX_PHOTO_BODY) {
          return NextResponse.json({ detail: "Photo exceeds 8 MB" }, { status: 413, headers });
        }
        const contentType = request.headers.get("content-type") ?? "";
        if (!contentType.startsWith("multipart/form-data;") || !request.body) {
          return NextResponse.json({ detail: "Select a clinical photo" }, { status: 422, headers });
        }
        const reader = request.body.getReader();
        const bytes = new Uint8Array(MAX_PHOTO_BODY);
        let length = 0;
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          if (length + value.byteLength > MAX_PHOTO_BODY) {
            void reader.cancel().catch(() => {});
            return NextResponse.json({ detail: "Photo exceeds 8 MB" }, { status: 413, headers });
          }
          bytes.set(value, length);
          length += value.byteLength;
        }
        init.body = bytes.subarray(0, length);
        init.headers = { ...init.headers, "Content-Type": contentType };
      } else if (path === "books") {
        const form = await request.formData();
        const file = form.get("file");
        if (!(file instanceof File) || !file.name.toLowerCase().endsWith(".pdf") || file.size === 0 || file.size > 50 * 1024 * 1024) return NextResponse.json({ detail: "Select a PDF between 1 byte and 50 MB" }, { status: 422, headers });
        init.body = form;
      } else if (path === "speech/transcribe") {
        const form = await request.formData();
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
      if (clinical && [403, 409, 422, 428, 429, 502, 503].includes(response.status)) {
        const detail = (await response.json().catch(() => ({}))).detail;
        if (typeof detail === "string" && detail.length < 300 && (
          response.status < 500 || /^(Clinical workflow failed at |Clinical photo analysis failed at |The clinical report could not be saved|Photo upload could not be completed)/.test(detail)
        )) return NextResponse.json({ detail }, { status: response.status, headers });
      }
      if (response.status === 502 && path.endsWith("/analyze")) {
        const detail = (await response.json().catch(() => ({}))).detail;
        if (typeof detail === "string" && analysisProviderErrors.has(detail)) return NextResponse.json({ detail }, { status: 502, headers });
      }
      // Key-management and missing-key errors carry safe, backend-written messages (never the key itself).
      // These backend messages name the field or rule that failed and never echo user text.
      if (path.startsWith("settings/ai") || path.startsWith("speech") || [409, 422, 428, 429].includes(response.status)) {
        const detail = (await response.json().catch(() => ({}))).detail;
        if (typeof detail === "string" && detail.length < 300) return NextResponse.json({ detail }, { status: response.status >= 500 && response.status !== 502 ? 503 : response.status, headers });
      }
      const messages = scope === "operator" ? operatorMessages : practitionerMessages;
      return NextResponse.json({ detail: messages[response.status] ?? "Backend service unavailable. Try again later." }, { status: response.status >= 500 && response.status !== 502 ? 503 : response.status, headers });
    }
    if (response.status === 204) return new NextResponse(null, { status: 204, headers });
    const type = response.headers.get("content-type") ?? "";
    if ((path.endsWith("/report/file") || path.endsWith("/prescription/file") || path === "ingestion/books/list.pdf" || (clinical && path.endsWith("/file"))) && (type.startsWith("application/pdf") || type.includes("wordprocessingml"))) {
      // The report file is binary: pass it through untouched, as a download.
      return new NextResponse(await response.arrayBuffer(), { status: 200, headers: { ...headers, "Content-Type": type, "Content-Disposition": response.headers.get("content-disposition") ?? "attachment" } });
    }
    if (clinical && type === "image/jpeg" && /\/(thumb|full)$/.test(path)) {
      return new NextResponse(await response.arrayBuffer(), { headers: {
        ...headers, "Content-Type": type, "X-Content-Type-Options": "nosniff",
      } });
    }
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
