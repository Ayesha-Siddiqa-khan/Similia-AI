"use client";

import { useQuery } from "@tanstack/react-query";

import type { BackendHealth } from "@/types";

/** Poll the local health proxy; used by the homepage status indicator. */
export function useBackendHealth(): {
  data: BackendHealth | undefined;
  isPending: boolean;
} {
  const query = useQuery<BackendHealth>({
    queryKey: ["backend-health"],
    queryFn: async ({ signal }) => {
      const response = await fetch("/api/health", { signal });
      if (!response.ok) throw new Error("Health check unavailable");
      return response.json() as Promise<BackendHealth>;
    },
    refetchInterval: 15_000,
    retry: 1,
  });
  return { data: query.data, isPending: query.isPending };
}
