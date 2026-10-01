import AppraisalForm from "./AppraisalForm";

export default async function AppraisalPage({ searchParams }: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const caseId = typeof params.caseId === "string" ? Number(params.caseId) || undefined : undefined;
  const candidateId = typeof params.candidateId === "string" ? Number(params.candidateId) || undefined : undefined;
  return <AppraisalForm key={`${caseId}:${candidateId}`} caseId={caseId} candidateId={candidateId} />;
}
