import { describe, expect, it } from "vitest";

import { describeBackendStatus } from "@/lib/health";

describe("describeBackendStatus", () => {
  it("labels a reachable backend as connected", () => {
    expect(describeBackendStatus("ok")).toEqual({
      label: "Backend connected",
      tone: "success",
    });
  });

  it("labels an unreachable backend as an error", () => {
    expect(describeBackendStatus("down")).toEqual({
      label: "Backend unreachable",
      tone: "error",
    });
  });

  it("labels the pending state as checking", () => {
    expect(describeBackendStatus("checking")).toEqual({
      label: "Checking backend…",
      tone: "muted",
    });
  });
});
