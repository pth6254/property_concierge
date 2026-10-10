"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { BriefcaseBusiness } from "lucide-react";
import { api } from "@/lib/api";
import type { CandidateAnalysis, PurchaseCase } from "@/lib/types";

type AnalysisType = CandidateAnalysis["analysis_type"];
const LABEL: Record<AnalysisType, string> = { appraisal: "시세", simulation: "자금", rights: "권리" };
const STATUS: Record<CandidateAnalysis["status"], string> = { completed: "저장됨", stale: "갱신 필요", pending: "진행 중", failed: "실패" };

/**
 * 후보에서 분석 화면으로 넘어오면 어느 케이스·후보를 분석 중인지, 결과가 후보에 실제로 저장됐는지를 보여준다.
 * 저장 여부는 화면 상태로 추측하지 않고 케이스를 다시 읽어 후보에 연결된 분석으로 확인한다.
 * refreshKey가 바뀌면(분석 완료 등) 다시 읽는다.
 */
export default function CaseContextBanner({ caseId, candidateId, analysis, refreshKey, historyId }: {
  caseId: number; candidateId?: number; analysis: AnalysisType; refreshKey?: string | number; historyId?: number;
}) {
  const [state, setState] = useState<{ key: string; item: PurchaseCase | null; failed: boolean } | null>(null);
  const key = `${caseId}:${candidateId}:${refreshKey ?? ""}`;
  useEffect(() => {
    let cancelled = false;
    api.caseOne(caseId)
      .then(item => { if (!cancelled) setState({ key, item, failed: false }); })
      .catch(() => { if (!cancelled) setState({ key, item: null, failed: true }); });
    return () => { cancelled = true; };
  }, [caseId, key]);
  const current = state?.key === key ? state : null;
  const candidate = current?.item?.properties?.find(property => property.id === candidateId);
  const linked = candidate?.analyses.find(item => item.analysis_type === analysis);
  const back = candidateId ? `/cases/${caseId}#candidate-${candidateId}` : `/cases/${caseId}`;
  const sameReport = historyId == null || linked?.reference_id == null || linked.reference_id === historyId;
  return <section aria-label="분석 중인 케이스 후보" className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm">
    <div className="min-w-0">
      <p className="flex items-center gap-2 font-semibold text-emerald-900"><BriefcaseBusiness size={16} aria-hidden="true" />
        {current?.item ? `${current.item.title}${candidate ? ` · ${candidate.name}` : ""}` : current?.failed ? "케이스 정보를 불러오지 못했습니다" : "케이스 정보를 불러오는 중…"}
      </p>
      {candidate && <p className="mt-0.5 text-xs text-emerald-900/80">
        {linked ? `후보의 ${LABEL[analysis]} 분석: ${STATUS[linked.status]}${linked.analyzed_at ? ` · ${new Date(linked.analyzed_at.replace(" ", "T")).toLocaleString("ko-KR")}` : ""}`
          : `후보에 저장된 ${LABEL[analysis]} 분석이 아직 없습니다.`}
        {!sameReport && " · 지금 보는 리포트는 후보에 연결된 최신 분석과 다른 기록입니다."}
      </p>}
      {current?.item && candidateId && !candidate && <p className="mt-0.5 text-xs text-amber-800">케이스에서 이 후보를 찾을 수 없습니다. 삭제됐을 수 있습니다.</p>}
    </div>
    <div className="flex flex-wrap gap-2">
      <Link href={back} className="rounded-lg bg-primary px-3 py-1.5 font-semibold text-white">후보로 돌아가기</Link>
      <Link href={`/cases/${caseId}/comparison`} className="rounded-lg border border-emerald-300 bg-white px-3 py-1.5 font-semibold text-primary">후보 비교</Link>
    </div>
  </section>;
}
