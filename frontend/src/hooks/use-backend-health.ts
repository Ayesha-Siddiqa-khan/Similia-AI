"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { BackendHealth } from "@/types";

/** Poll the local health proxy; used by the homepage status indicator. */
export function useBackendHealth(): {
  data: BackendHealth | undefined;
  isPending: boolean;
} {
  const client = useQueryClient();
  const previous = useRef<BackendHealth>(undefined);
  const query = useQuery<BackendHealth>({
    queryKey: ["backend-health"],
    queryFn: async ({ signal }) => {
      const response = await fetch("/api/health", { signal, cache: "no-store" });
      if (!response.ok) throw new Error("Health check unavailable");
      return response.json() as Promise<BackendHealth>;
    },
    refetchInterval: 15_000,
    refetchOnWindowFocus: true,
    retry: 1,
  });
  const health = query.data;
  useEffect(() => {
    const last = previous.current;
    if (query.isError) {
      previous.current = { backend: "down" };
      return;
    }
    if (!health) return;
    previous.current = health;
    if (health.backend === "ok" && last && (
      last.backend === "down" || (health.instanceId && last.instanceId !== health.instanceId)
    )) {
      void client.invalidateQueries({
        predicate: (entry) => entry.queryKey[0] !== "backend-health" && entry.meta?.autoRefresh !== false,
      }, { cancelRefetch: false });
    }
  }, [client, health, query.isError]);
  return { data: query.data, isPending: query.isPending };
}
