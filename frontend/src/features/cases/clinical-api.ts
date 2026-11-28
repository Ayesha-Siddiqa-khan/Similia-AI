import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/backend";

export type ReportStage = "research" | "assessment" | "final";
export type ClinicalReport = {
  id: string;
  stage: ReportStage;
  locale: "en" | "ur";
  status: "research" | "draft" | "reviewed" | "signed" | "translation";
  source_id: string | null;
  created_at: string;
  stale: boolean;
  urgent: boolean;
  decision: "accepted" | "modified" | "rejected" | "independent" | null;
  editable: Record<string, string | null> | null;
  blocks: { kind: string; text: string; ltr: boolean }[];
};

export const clinicalPath = (id: string) => `/workspace/workflow/${id}`;
export const workflowEndpoint = (id: string) => `cases/${id}/workflow`;
export const clinicalQueryKey = (id: string) => ["clinical-workflow", id] as const;
export function useClinicalWorkflow(id: string, metadataOnly = false) {
  return useQuery({
    queryKey: [...clinicalQueryKey(id), metadataOnly],
    queryFn: ({ signal }) => api<{ enabled: boolean; reports: ClinicalReport[] }>(
      workflowEndpoint(id) + (metadataOnly ? "?metadata_only=true" : ""), { signal },
    ),
    retry: false,
  });
}
