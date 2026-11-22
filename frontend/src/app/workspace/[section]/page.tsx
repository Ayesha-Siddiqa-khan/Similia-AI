import { notFound, redirect } from "next/navigation";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { WorkspacePage } from "@/features/workspace";
import { isOperator } from "@/lib/auth";
import { createClient } from "@/lib/supabase/server";
const valid = ["dashboard", "knowledge", "books", "ingestion", "chunks", "search", "case", "patients", "ai", "settings"];
const practitionerSections = ["case", "patients", "ai"];
async function Section({ params }: { params: Promise<{ section: string }> }) {
  const { section } = await params;
  if (!valid.includes(section)) notFound();
  if (!practitionerSections.includes(section)) {
    // Knowledge-base pages are operator-only; practitioners land on their patients instead.
    const { data } = await (await createClient()).auth.getUser();
    if (data.user && !isOperator(data.user.app_metadata)) redirect("/workspace/patients");
  }
  return <WorkspacePage section={section} />;
}
export default function Page({ params }: { params: Promise<{ section: string }> }) {
  return <Suspense fallback={<Loading />}><Section params={params} /></Suspense>;
}
