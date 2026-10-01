import ExploreWorkspace from "./ExploreWorkspace";

export default async function ExplorePage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const caseId = typeof params.case_id === "string" && /^[1-9]\d{0,14}$/.test(params.case_id) ? params.case_id : "";
  return <ExploreWorkspace key={caseId} initialCaseId={caseId} />;
}
