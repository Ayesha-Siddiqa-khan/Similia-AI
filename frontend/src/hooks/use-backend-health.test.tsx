import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { type ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useBackendHealth } from "./use-backend-health";

afterEach(() => vi.unstubAllGlobals());

it("refreshes saved data after a restart and skips explicitly requested AI queries", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryDefaults(["report-urdu"], { meta: { autoRefresh: false } });
  client.setQueryData(["report-urdu", "example"], {});
  client.setQueryData(["ai-settings"], {});
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
    JSON.stringify({ backend: "ok", instanceId: "before" }),
  )));
  const hook = renderHook(useBackendHealth, {
    wrapper: ({ children }: { children: ReactNode }) =>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>,
  });
  await waitFor(() => expect(hook.result.current.data?.instanceId).toBe("before"));
  expect(client.getQueryState(["ai-settings"])?.isInvalidated).toBe(false);

  act(() => client.setQueryData(["backend-health"], { backend: "ok", instanceId: "after" }));
  await waitFor(() => expect(client.getQueryState(["ai-settings"])?.isInvalidated).toBe(true));
  expect(client.getQueryState(["report-urdu", "example"])?.isInvalidated).toBe(false);
});
