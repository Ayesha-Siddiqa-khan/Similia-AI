import { describe, expect, it, vi } from "vitest";
import { isOperator, isPractitioner, sameOrigin } from "./auth";
describe("authorization boundary", () => {
  it("requires the operator role from verified app metadata", () => {
    expect(isOperator(undefined)).toBe(false);
    expect(isOperator({ similia_role: "patient" })).toBe(false);
    expect(isOperator({ similia_role: "operator" })).toBe(true);
    expect(isOperator({ similia_role: "admin" })).toBe(true);
  });
  it("lets practitioners and operators take cases but not other roles", () => {
    expect(isPractitioner({ similia_role: "practitioner" })).toBe(true);
    expect(isPractitioner({ similia_role: "operator" })).toBe(true);
    expect(isPractitioner({ similia_role: "patient" })).toBe(false);
    expect(isOperator({ similia_role: "practitioner" })).toBe(false);
  });
  it("rejects cross-origin and missing-origin mutations", () => {
    expect(sameOrigin(new Request("http://localhost:3000/api/backend/books", { headers: { origin: "https://foreign.example" } }))).toBe(false);
    expect(sameOrigin(new Request("http://localhost:3000/api/backend/books"))).toBe(false);
    expect(sameOrigin(new Request("http://localhost:3000/api/backend/books", { headers: { origin: "http://localhost:3000" } }))).toBe(true);
  });
  it("uses the launcher origin when Next normalizes the desktop request URL", () => {
    vi.stubEnv("SIMILIA_DESKTOP_ORIGIN", "http://127.0.0.1:41000");
    try {
      const requestUrl = "http://localhost:41000/api/backend/cases";
      expect(sameOrigin(new Request(requestUrl, { headers: { origin: "http://127.0.0.1:41000" } }))).toBe(true);
      expect(sameOrigin(new Request(requestUrl, { headers: { origin: "http://localhost:41000" } }))).toBe(false);
    } finally {
      vi.unstubAllEnvs();
    }
  });
});
