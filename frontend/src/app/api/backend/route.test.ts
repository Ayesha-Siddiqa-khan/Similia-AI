import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// The proxy is the only door from the browser to the backend. These tests check who may use it,
// which paths are reachable, and what the browser is allowed to learn from failures.
const session = vi.hoisted(() => ({ signedIn: true, role: "practitioner" as string | null }));
vi.mock("@/lib/supabase/server", () => ({
  createClient: async () => ({
    auth: {
      getUser: async () => ({
        data: { user: session.signedIn ? { app_metadata: session.role ? { similia_role: session.role } : {} } : null },
        error: null,
      }),
      getSession: async () => ({ data: { session: { access_token: "test-token" } } }),
    },
  }),
}));
vi.mock("@/lib/graphql/client", () => ({ getGraphQLClient: () => ({ request: async () => ({ health: "ok" }) }) }));

import { DELETE, GET, PATCH, POST, PUT } from "./[...path]/route";

const ID = "123e4567-e89b-42d3-a456-426614174000";
const ORIGIN = "http://localhost:3000";
const call = (handler: typeof GET, method: string, path: string[], init: RequestInit & { origin?: string | null } = {}) => {
  const { origin = ORIGIN, ...rest } = init;
  const headers = new Headers(rest.headers);
  if (origin) headers.set("origin", origin);
  return handler(new Request(`${ORIGIN}/api/backend/${path.join("/")}`, { ...rest, method, headers }), { params: Promise.resolve({ path }) });
};
let backend: ReturnType<typeof vi.fn>;
// A fresh Response per call: a response body can only be read once.
const answer = (status: number, body: unknown) => { backend.mockImplementation(async () => new Response(JSON.stringify(body), { status })); };

beforeEach(() => {
  session.signedIn = true; session.role = "practitioner";
  process.env.NEXT_PUBLIC_SUPABASE_URL = "http://localhost:54321";
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "publishable-test";
  backend = vi.fn();
  vi.stubGlobal("fetch", backend);
  answer(200, []);
});
afterEach(() => { vi.unstubAllGlobals(); });

it("allows for cold speech worker startup and model loading while forwarding authentication", async () => {
  const timeout = vi.spyOn(AbortSignal, "timeout");
  try {
    expect((await call(POST, "POST", ["speech", "load"])).status).toBe(200);
    expect(timeout).toHaveBeenCalledWith(250_000);
    expect(backend.mock.calls[0][1].headers.Authorization).toBe("Bearer test-token");
    session.signedIn = false;
    expect((await call(POST, "POST", ["speech", "load"])).status).toBe(401);
    expect(backend).toHaveBeenCalledTimes(1);
  } finally {
    timeout.mockRestore();
  }
});

describe("which paths are reachable", () => {
  it("refuses anything that is not on the allow-list, including path tricks", async () => {
    for (const [handler, method, path] of [
      [GET, "GET", ["admin"]], [GET, "GET", ["cases", "..", "books"]], [GET, "GET", ["cases", `${ID}`, "secret"]],
      [DELETE, "DELETE", ["cases", ID]], [DELETE, "DELETE", ["patients"]], [POST, "POST", ["patients", ID]],
      [PATCH, "PATCH", ["settings", "ai"]],
    ] as const) {
      const response = await call(handler, method, [...path]);
      expect(response.status, `${method} ${path.join("/")}`).toBe(404);
    }
    expect(backend).not.toHaveBeenCalled();
  });
  it("allows the practitioner endpoints the app uses", async () => {
    for (const [handler, method, path] of [
      [GET, "GET", ["patients"]], [GET, "GET", ["cases", ID]], [PUT, "PUT", ["cases", ID, "symptoms"]], [PATCH, "PATCH", ["cases", ID]],
      [POST, "POST", ["cases", ID, "reopen"]], [POST, "POST", ["cases", ID, "analyze"]], [DELETE, "DELETE", ["settings", "ai"]],
      [POST, "POST", ["settings", "ai", "activate"]], [POST, "POST", ["cases", ID, "report", "urdu"]],
      [GET, "GET", ["cases", ID, "review"]], [GET, "GET", ["cases", ID, "prescription", "file"]],
    ] as const) {
      const response = await call(handler, method, [...path], method === "GET" || method === "DELETE" ? {} : { body: "{}" });
      expect(response.status, `${method} ${path.join("/")}`).toBe(200);
    }
  });
});

describe("the Urdu report endpoint", () => {
  it("is reachable by POST for a practitioner, with the analysis id passed through", async () => {
    answer(200, { analysis_id: "a" });
    const response = await POST(new Request(`${ORIGIN}/api/backend/cases/${ID}/report/urdu?analysis_id=${ID}`, { method: "POST", headers: { origin: ORIGIN } }), { params: Promise.resolve({ path: ["cases", ID, "report", "urdu"] }) });
    expect(response.status).toBe(200);
    expect(String(backend.mock.calls[0][0])).toBe(`http://localhost:8000/api/cases/${ID}/report/urdu?analysis_id=${ID}`);
  });
  it("is refused with 403 for an account with no role", async () => {
    session.role = null;
    expect((await call(POST, "POST", ["cases", ID, "report", "urdu"])).status).toBe(403);
    expect(backend).not.toHaveBeenCalled();
  });
  it("is not readable with GET", async () => {
    expect((await call(GET, "GET", ["cases", ID, "report", "urdu"])).status).toBe(404);
    expect(backend).not.toHaveBeenCalled();
  });
});

describe("prescription download proxy", () => {
  it("streams binary PDF attachment for prescription/file", async () => {
    backend.mockImplementation(async () => new Response(new Uint8Array([37, 80, 68, 70]), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="prescription-P1.pdf"',
      },
    }));
    const response = await call(GET, "GET", ["cases", ID, "prescription", "file"]);
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("application/pdf");
    expect(response.headers.get("Content-Disposition")).toBe('attachment; filename="prescription-P1.pdf"');
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([37, 80, 68, 70]));
  });
});

describe("clinical workflow proxy", () => {
  it("forwards private photo bytes and disables caching", async () => {
    backend.mockImplementation(async () => new Response(new Uint8Array([255, 216, 255]), {
      headers: { "Content-Type": "image/jpeg" },
    }));
    const response = await call(GET, "GET", ["cases", ID, "photos", ID, "full"]);
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    expect(response.headers.get("X-Content-Type-Options")).toBe("nosniff");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([255, 216, 255]));
  });

  it("requires authentication and the same origin for clinical mutations", async () => {
    const sign = ["cases", ID, "workflow", "final", "sign"];
    expect((await call(POST, "POST", sign, { origin: "https://elsewhere.invalid" })).status).toBe(403);
    session.signedIn = false;
    expect((await call(POST, "POST", sign)).status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
  });

  it("forwards a multipart clinical photo and rejects oversized uploads", async () => {
    const boundary = "clinical-fixture";
    const headers = { "Content-Type": `multipart/form-data; boundary=${boundary}` };
    const payload = [
      `--${boundary}`, 'Content-Disposition: form-data; name="file"; filename="photo.jpg"',
      "Content-Type: image/jpeg", "", "fixture",
      `--${boundary}`, 'Content-Disposition: form-data; name="body_site"', "", "hand",
      `--${boundary}--`, "",
    ].join("\r\n");
    const path = ["cases", ID, "photos"];
    expect((await call(POST, "POST", path, { body: payload, headers })).status).toBe(200);
    const init = backend.mock.calls[0][1];
    expect(init.headers["Content-Type"]).toBe(headers["Content-Type"]);
    expect(new TextDecoder().decode(init.body)).toBe(payload);
    expect((await call(POST, "POST", path, {
      body: "x".repeat(9 * 1024 * 1024), headers,
    })).status).toBe(413);
    expect(backend).toHaveBeenCalledTimes(1);
  });
});

describe("who may use it", () => {
  it("answers 401 when nobody is signed in, without calling the backend", async () => {
    session.signedIn = false;
    expect((await call(GET, "GET", ["patients"])).status).toBe(401);
    expect(backend).not.toHaveBeenCalled();
  });
  it("answers 403 for an account with no Similia role", async () => {
    session.role = null;
    expect((await call(GET, "GET", ["patients"])).status).toBe(403);
    expect(backend).not.toHaveBeenCalled();
  });
  it("keeps knowledge-base endpoints for operators only", async () => {
    const denied = await call(GET, "GET", ["books"]);
    expect(denied.status).toBe(403);
    expect((await denied.json()).detail).toMatch(/operator role/);
    session.role = "operator";
    expect((await call(GET, "GET", ["books"])).status).toBe(200);
    expect((await call(GET, "GET", ["patients"])).status).toBe(200); // operators may also take cases
  });
  it("sends the signed-in user's token to the backend (and nothing from the browser's headers)", async () => {
    await call(GET, "GET", ["patients"], { headers: { authorization: "Bearer attacker" } });
    const [, init] = backend.mock.calls[0];
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer test-token");
  });
});

describe("request safety", () => {
  it("rejects changes that do not come from the site itself (cross-site request forgery)", async () => {
    for (const origin of ["https://evil.example", null]) {
      const response = await call(PUT, "PUT", ["cases", ID, "symptoms"], { body: "{}", origin });
      expect(response.status).toBe(403);
    }
    expect(backend).not.toHaveBeenCalled();
  });
  it("refuses an oversized JSON body", async () => {
    const response = await call(PUT, "PUT", ["cases", ID, "symptoms"], { body: JSON.stringify({ x: "a".repeat(1024 * 1024 + 1) }) });
    expect(response.status).toBe(413);
    expect(backend).not.toHaveBeenCalled();
  });
});

describe("what the browser learns from failures", () => {
  it("shows only the fixed provider rejection message for analysis failures", async () => {
    const path = ["cases", ID, "analyze"];
    for (const detail of [
      "The AI provider rejected the analysis. Check your key, model and billing in AI Settings.",
      "Claude rejected the analysis because of a billing issue. Check billing and available credits in the Anthropic Console, then try again.",
      "The source library could not be searched. Try again later.",
      "Analysis failed while interpreting the retrieved sources. Try again later.",
    ]) {
      answer(502, { detail });
      const rejected = await call(POST, "POST", path);
      expect(rejected.status).toBe(502);
      expect((await rejected.json()).detail).toBe(detail);
    }
    answer(502, { detail: "Private provider error" });
    const unexpected = await call(POST, "POST", path);
    expect((await unexpected.json()).detail).toBe("The analysis service failed. Try again later.");
  });
  it("shows the backend's own explanation for conflicts and validation problems", async () => {
    answer(409, { detail: "This case is signed off and locked. Reopen it to make changes." });
    const locked = await call(PUT, "PUT", ["cases", ID, "symptoms"], { body: "{}" });
    expect(locked.status).toBe(409);
    expect((await locked.json()).detail).toMatch(/signed off and locked/);
    answer(422, { detail: "symptoms.0.duration: String should have at most 500 characters" });
    const invalid = await call(PUT, "PUT", ["cases", ID, "symptoms"], { body: "{}" });
    expect((await invalid.json()).detail).toMatch(/symptoms\.0\.duration/);
  });
  it("hides server errors behind a generic message", async () => {
    answer(500, { detail: "Traceback: password authentication failed for user postgres" });
    const response = await call(GET, "GET", ["patients"]);
    expect(response.status).toBe(503);
    expect(JSON.stringify(await response.json())).not.toMatch(/Traceback|postgres|password/);
  });
  it("turns an unreachable backend into a clear 503", async () => {
    backend.mockRejectedValue(new TypeError("fetch failed: ECONNREFUSED 127.0.0.1:8000"));
    const response = await call(GET, "GET", ["patients"]);
    expect(response.status).toBe(503);
    expect(JSON.stringify(await response.json())).not.toMatch(/ECONNREFUSED|127\.0\.0\.1/);
  });
});

describe("ingestion endpoints", () => {
  const operatorCalls = [
    [GET, "GET", ["ingestion", "overview"]], [GET, "GET", ["books", ID, "ingestion"]], [GET, "GET", ["books", ID, "chunks"]], [GET, "GET", ["books", ID, "text"]],
    [POST, "POST", ["books", ID, "prepare"]], [POST, "POST", ["books", ID, "ingest"]], [POST, "POST", ["ingestion-jobs", ID, "pause"]],
  ] as const;
  const init = (method: string) => (method === "GET" ? {} : { body: JSON.stringify({ confirmed: true }) });
  it("lets an operator read and control book ingestion", async () => {
    session.role = "operator";
    for (const [handler, method, path] of operatorCalls) {
      const response = await call(handler, method, [...path], init(method));
      expect(response.status, `${method} ${path.join("/")}`).toBe(200);
    }
    expect(backend).toHaveBeenCalledTimes(operatorCalls.length);
  });
  it("forwards the query string and the confirmation body untouched", async () => {
    session.role = "operator";
    await call(GET, "GET", ["books", ID, "chunks"], {});
    await call(POST, "POST", ["books", ID, "ingest"], { body: JSON.stringify({ confirmed: true }) });
    const post = backend.mock.calls[1];
    expect(post[1].body).toBe(JSON.stringify({ confirmed: true }));
  });
  it("answers 403 to a practitioner without calling the backend", async () => {
    session.role = "practitioner";
    for (const [handler, method, path] of operatorCalls) {
      const response = await call(handler, method, [...path], init(method));
      expect(response.status, `${method} ${path.join("/")}`).toBe(403);
    }
    expect(backend).not.toHaveBeenCalled();
  });
  it("allows the automatic-resume endpoints for operators only and forwards the body untouched", async () => {
    session.role = "operator";
    const body = JSON.stringify({ book_ids: [ID], confirmed: true });
    expect((await call(POST, "POST", ["ingestion", "auto"], { body })).status).toBe(200);
    expect((await call(POST, "POST", ["ingestion", "auto", "stop"], { body: JSON.stringify({ book_ids: [ID] }) })).status).toBe(200);
    expect(backend.mock.calls[0][0]).toMatch(/\/api\/ingestion\/auto$/);
    expect(backend.mock.calls[0][1].body).toBe(body);
    expect(backend.mock.calls[1][1].body).toBe(JSON.stringify({ book_ids: [ID] }));
    expect(backend).toHaveBeenCalledTimes(2);
    expect((await call(GET, "GET", ["ingestion", "auto"])).status).toBe(404);
    expect((await call(GET, "GET", ["ingestion", "auto", "stop"])).status).toBe(404);
    expect(backend).toHaveBeenCalledTimes(2);
  });
  it("answers 403 to a practitioner-only account on the automatic-resume endpoints", async () => {
    session.role = "practitioner";
    expect((await call(POST, "POST", ["ingestion", "auto"], { body: JSON.stringify({ book_ids: [ID], confirmed: true }) })).status).toBe(403);
    expect((await call(POST, "POST", ["ingestion", "auto", "stop"], { body: "{}" })).status).toBe(403);
    expect(backend).not.toHaveBeenCalled();
  });
  it("passes the book-list PDF through as a download for an operator", async () => {
    session.role = "operator";
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46]);
    backend.mockImplementation(async () => new Response(bytes, { status: 200, headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="ingestion-book-list.pdf"' } }));
    const response = await call(GET, "GET", ["ingestion", "books", "list.pdf"]);
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toContain("ingestion-book-list.pdf");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
    expect(String(backend.mock.calls[0][0])).toBe("http://localhost:8000/api/ingestion/books/list.pdf");
  });
  it("keeps the book-list PDF for operators only and refuses other methods", async () => {
    session.role = "practitioner";
    expect((await call(GET, "GET", ["ingestion", "books", "list.pdf"])).status).toBe(403);
    session.role = "operator";
    expect((await call(POST, "POST", ["ingestion", "books", "list.pdf"], { body: "{}" })).status).toBe(404);
    expect(backend).not.toHaveBeenCalled();
  });
  it("answers 404 to unknown ingestion variants, even for an operator", async () => {
    session.role = "operator";
    for (const [handler, method, path] of [
      [POST, "POST", ["books", ID, "delete"]], [GET, "GET", ["books", ID, "delete"]], [DELETE, "DELETE", ["books", ID]],
      [POST, "POST", ["ingestion-jobs", ID, "cancel"]], [POST, "POST", ["ingestion", "overview"]], [GET, "GET", ["books", "not-a-uuid", "ingestion"]],
    ] as const) {
      const response = await call(handler, method, [...path], init(method));
      expect(response.status, `${method} ${path.join("/")}`).toBe(404);
    }
    expect(backend).not.toHaveBeenCalled();
  });
});

describe("patient safeguard endpoints", () => {
  it("lets a practitioner read consents, history, export and earlier analyses", async () => {
    for (const path of [["patients", ID, "consents"], ["patients", ID, "history"], ["patients", ID, "export"], ["cases", ID, "analyses"]]) {
      expect((await call(GET, "GET", path)).status, path.join("/")).toBe(200);
    }
  });
  it("lets a practitioner record and withdraw consent", async () => {
    answer(201, { id: ID });
    expect((await call(POST, "POST", ["patients", ID, "consent"])).status).toBe(201);
    answer(200, { id: ID });
    expect((await call(POST, "POST", ["patients", ID, "consent", "withdraw"])).status).toBe(200);
  });
  it("erases a patient with the confirmation passed through and answers 204", async () => {
    backend.mockImplementation(async () => new Response(null, { status: 204 }));
    const response = await call(DELETE, "DELETE", ["patients", ID], { headers: {} });
    expect(response.status).toBe(204);
    const withQuery = await call(DELETE, "DELETE", ["patients", ID]);
    expect(withQuery.status).toBe(204);
  });
  it("passes the confirm_identifier query string to the backend", async () => {
    backend.mockImplementation(async () => new Response(null, { status: 204 }));
    const request = new Request(`${ORIGIN}/api/backend/patients/${ID}?confirm_identifier=P-1`, { method: "DELETE", headers: { origin: ORIGIN } });
    expect((await DELETE(request, { params: Promise.resolve({ path: ["patients", ID] }) })).status).toBe(204);
    expect(String(backend.mock.calls[0][0]).endsWith(`/api/patients/${ID}?confirm_identifier=P-1`)).toBe(true);
  });
  it("refuses an account with no Similia role", async () => {
    session.role = null;
    for (const [handler, method, path] of [[GET, "GET", ["patients", ID, "export"]], [POST, "POST", ["patients", ID, "consent", "withdraw"]], [DELETE, "DELETE", ["patients", ID]]] as const) {
      expect((await call(handler, method, [...path])).status, `${method} ${path.join("/")}`).toBe(403);
    }
    expect(backend).not.toHaveBeenCalled();
  });
  it("still refuses deleting every patient or a case", async () => {
    expect((await call(DELETE, "DELETE", ["patients"])).status).toBe(404);
    expect((await call(DELETE, "DELETE", ["cases", ID])).status).toBe(404);
    expect(backend).not.toHaveBeenCalled();
  });
});

describe("report file download", () => {
  it("passes a PDF through untouched with its download headers", async () => {
    const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]);
    backend.mockImplementation(async () => new Response(bytes, { status: 200, headers: { "content-type": "application/pdf", "content-disposition": 'attachment; filename="case-11111111-report-en.pdf"' } }));
    const response = await call(POST, "POST", ["cases", ID, "report", "file"], { body: JSON.stringify({ format: "pdf", lang: "en" }) });
    expect(response.status).toBe(200);
    expect(response.headers.get("content-type")).toBe("application/pdf");
    expect(response.headers.get("content-disposition")).toContain("case-11111111-report-en.pdf");
    expect(response.headers.get("cache-control")).toBe("private, no-store");
    expect(new Uint8Array(await response.arrayBuffer())).toEqual(bytes);
  });
  it("is refused with 403 without a role and 404 for GET", async () => {
    session.role = null;
    expect((await call(POST, "POST", ["cases", ID, "report", "file"], { body: "{}" })).status).toBe(403);
    session.role = "practitioner";
    expect((await call(GET, "GET", ["cases", ID, "report", "file"])).status).toBe(404);
  });
});
