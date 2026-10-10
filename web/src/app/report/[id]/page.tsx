import SavedReport from "./SavedReport";

/** 검색 조건은 서버에서 읽어 넘긴다. 클라이언트 useSearchParams는 정적 렌더 경계를 요구해 페이지를 비울 수 있다. */
export default async function SavedReportPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const caseId = typeof params.caseId === "string" ? Number(params.caseId) || undefined : undefined;
  const candidateId = typeof params.candidateId === "string" ? Number(params.candidateId) || undefined : undefined;
  return <SavedReport caseId={caseId} candidateId={candidateId} />;
}
