import type { BackendStatus } from "@/types";

interface StatusPresentation {
  label: string;
  tone: "success" | "error" | "muted";
}

/** Map a backend status to its display label and Tailwind tone. */
export function describeBackendStatus(status: BackendStatus): StatusPresentation {
  switch (status) {
    case "ok":
      return { label: "Backend connected", tone: "success" };
    case "down":
      return { label: "Backend unreachable", tone: "error" };
    case "checking":
      return { label: "Checking backend…", tone: "muted" };
  }
}
