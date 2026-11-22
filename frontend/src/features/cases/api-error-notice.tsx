import Link from "next/link";
import { Notice } from "@/components/ui";
import { ApiError } from "@/lib/backend";

/** An error banner. When the doctor has no AI key yet (HTTP 428) it links to AI Settings. */
export function ApiErrorNotice({ error }: { error: Error }) {
  const needsKey = error instanceof ApiError && error.status === 428;
  return (
    <Notice error={!needsKey}>
      {error.message}{needsKey && <> <Link className="text-link" href="/workspace/ai">Open AI Settings</Link></>}
    </Notice>
  );
}
