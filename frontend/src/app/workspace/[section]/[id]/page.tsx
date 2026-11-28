import { connection } from "next/server";
import { notFound } from "next/navigation";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { WorkspacePage } from "@/features/workspace";

type Params = Promise<{ section: string; id: string }>;
const detailSections = ["patients", "case", "report", "workflow"];
async function Detail({ params }: { params: Params }) {
  await connection(); // render per request: these screens read the clock (TanStack Query) and live data
  const { section, id } = await params;
  if (!detailSections.includes(section) || !/^[a-f0-9-]{36}$/.test(id)) notFound();
  return <WorkspacePage section={section} id={id} />;
}
export default function Page({ params }: { params: Params }) {
  return <Suspense fallback={<Loading />}><Detail params={params} /></Suspense>;
}
