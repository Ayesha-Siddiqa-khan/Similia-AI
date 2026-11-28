import { Suspense } from "react";
import { redirect } from "next/navigation";
import { connection } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { isOperator, isPractitioner } from "@/lib/auth";
import { AppShell } from "@/components/app-shell";
import { Loading, Notice } from "@/components/ui";

async function Protected({ children }: { children: React.ReactNode }) {
  await connection(); // render per request: reading the session compares the token expiry against the clock
  if (!process.env.NEXT_PUBLIC_SUPABASE_URL || !process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY) redirect("/login");
  const client = await createClient();
  const { data, error } = await client.auth.getUser().catch(() => ({ data: { user: null }, error: true }));
  if (error || !data.user) redirect("/login");
  if (!isPractitioner(data.user.app_metadata)) return <AppShell accountId={data.user.id} userLabel={data.user.email ?? "Account"}><Notice error>This account does not have Similia access. Ask the project administrator to assign the trusted practitioner or operator role.</Notice></AppShell>;
  // Practitioners see only the patient and case workspaces; operators also manage the knowledge base.
  const sectionIds = isOperator(data.user.app_metadata) ? undefined : ["case", "patients", "ai"];
  return <AppShell accountId={data.user.id} userLabel={data.user.email ?? "Operator"} sectionIds={sectionIds}>{children}</AppShell>;
}
export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  return <Suspense fallback={<Loading />}><Protected>{children}</Protected></Suspense>;
}
