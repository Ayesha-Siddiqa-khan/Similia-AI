import { Notice } from "@/components/ui";

export type SearchMode = "semantic" | "keyword" | "hybrid";

export const searchModeOptions: { value: SearchMode; label: string }[] = [
  { value: "semantic", label: "Semantic (meaning-based, voyage-4-lite)" },
  { value: "keyword", label: "Keyword (word matching)" },
  { value: "hybrid", label: "Hybrid (meaning + keyword)" },
];

const names: Record<string, string> = {
  semantic: "Semantic", keyword: "Keyword", hybrid: "Hybrid",
  mixed: "Mixed", not_run: "Skipped", unknown: "Unknown",
};

/** Which search method actually ran, and why it differs from the one that was asked for. */
export function SearchMethodNotice({ requested, used, reason }: { requested?: string; used?: string; reason?: string | null }) {
  if (!used) return null;
  const differs = requested && requested !== used;
  return (
    <>
      <p className="fine-print" data-testid="search-method">Search method used: <strong>{names[used] ?? used}</strong>{differs ? <> (you asked for {names[requested] ?? requested})</> : null}.{used === "hybrid" ? " Scores are rank scores from combining both searches, not similarities." : ""}</p>
      {differs && used === "keyword" && <Notice error>{names[requested] ?? requested} search could not be used, so Keyword matching ran instead. {reason ?? ""}</Notice>}
      {used === "mixed" && <Notice error>Meaning-based search ran for some queries. The remaining queries used keyword fallback. {reason ?? ""}</Notice>}
    </>
  );
}
