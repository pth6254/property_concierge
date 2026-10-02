"use client";

import Link from "next/link";
import { candidateSimulationSeed } from "@/lib/candidateSimulationSeed";
import { setSessionValue } from "@/lib/sessionStore";
import type { BuyerProfile, CaseProperty, DecisionAssessmentStatus, DecisionAxis, DecisionEvidence } from "@/lib/types";

const statuses: Record<DecisionAssessmentStatus, { label: string; style: string }> = {
  confirmed: { label: "등록 자료 확인", style: "bg-emerald-50 text-emerald-800" },
  warning: { label: "주의·재검토", style: "bg-amber-50 text-amber-900" },
  unknown: { label: "미확인", style: "bg-slate-100 text-slate-700" },
  stale: { label: "갱신 필요", style: "bg-amber-50 text-amber-900" },
  error: { label: "분석 실패", style: "bg-red-50 text-red-800" },
  pending: { label: "분석 중", style: "bg-blue-50 text-blue-800" },
};
const sources = { user_input: "사용자 입력", calculation: "계산 결과", document: "문서 분석", workflow: "작업 기록", official_data: "공식 실거래 자료" };
const sourceStates: Record<string, string> = { current: "최근 사용자 확인", changed: "저장 후 변경", needs_confirmation: "재확인 필요", missing: "원본 미확인" };

export function DecisionStatus({ status }: { status: DecisionAssessmentStatus }) {
  const display = statuses[status];
  return <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${display.style}`}>{display.label}</span>;
}

function evidenceValue(evidence: DecisionEvidence) {
  if (evidence.value === null) return "미확인";
  if (evidence.key === "listing_confirmation") return sourceStates[String(evidence.value)] ?? "미확인";
  if (typeof evidence.value === "boolean") return evidence.value ? "예" : "아니오";
  return `${typeof evidence.value === "number" ? evidence.value.toLocaleString("ko-KR") : evidence.value}${evidence.unit}`;
}

export default function DecisionAxisCard({ axis, property, caseId, profile }: {
  axis: DecisionAxis; property: CaseProperty; caseId: number; profile: BuyerProfile;
}) {
  const href = axis.review_target === "profile" ? `/cases/${caseId}#buyer-profile`
    : axis.review_target === "checklist" ? `/cases/${caseId}#candidate-checklist-${property.id}`
    : axis.review_target === "execution" ? `/cases/${caseId}/execution`
    : axis.review_target === "appraisal" ? `/appraisal?caseId=${caseId}&candidateId=${property.id}`
    : `/${axis.review_target}`;
  const prepare = () => {
    if (axis.review_target === "simulation") setSessionValue("simFromListing", JSON.stringify(candidateSimulationSeed(property, caseId, profile)));
    if (axis.review_target === "rights") setSessionValue("rightsCandidate", JSON.stringify({
      market_price: property.appraisal?.estimated_value ?? property.asking_price,
      address: property.address, case_id: caseId, candidate_id: property.id,
    }));
  };
  return <section aria-label={`${property.name} ${axis.label}`} className="flex min-w-0 flex-col rounded-xl border border-slate-200 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-lg font-bold">{axis.label}</h3><DecisionStatus status={axis.status} /></div>
    <p className="mt-3 font-semibold">{axis.headline}</p>
    <p className="mt-2 text-sm leading-relaxed text-slate-600">{axis.explanation}</p>
    {axis.missing.length > 0 && <div className="mt-3 rounded bg-amber-50 p-3 text-sm text-amber-900"><p className="font-semibold">확인할 정보</p><ul className="mt-1 list-inside list-disc">{axis.missing.map(item => <li key={item}>{item}</li>)}</ul></div>}
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer font-semibold text-slate-700">판단 근거 · {axis.evidence.length}개</summary>
      <dl className="mt-3 max-h-80 space-y-3 overflow-auto print:max-h-none print:overflow-visible">{axis.evidence.map(item => <div key={item.key} className="break-words border-b border-slate-100 pb-2">
        <dt className="text-slate-500">{item.label}</dt><dd className="mt-1 font-medium">{evidenceValue(item)}</dd>
        <dd className="mt-1 text-xs text-slate-500">{sources[item.source]} · 기준 시각 {item.as_of || "미확인"}</dd>
        {item.provenance && <dd className="mt-2 space-y-1 text-xs text-slate-600">
          {typeof item.provenance.selection_reason === "string" && <p>선정 근거: {item.provenance.selection_reason}</p>}
          {typeof item.provenance.area_difference_m2 === "number" && <p>대상 면적 차이: {item.provenance.area_difference_m2}㎡</p>}
          {typeof item.provenance.floor === "string" && <p>거래 층: {item.provenance.floor}</p>}
          {typeof item.provenance.transaction_ref === "string" && <p className="break-all">거래 지문: {item.provenance.transaction_ref}</p>}
          {typeof item.provenance.source_sigungu_code === "string" && <p>조회 지역 코드 {item.provenance.source_sigungu_code} · 거래 월 {typeof item.provenance.source_deal_month === "string" ? item.provenance.source_deal_month : "미확인"}</p>}
          {item.provenance.reference_url === "https://rt.molit.go.kr/" && <p><a href={item.provenance.reference_url} target="_blank" rel="noopener noreferrer" className="text-primary underline">국토부 실거래 공개자료 확인</a> · 거래 지문은 서비스 식별값입니다.</p>}
          {typeof item.provenance.document_sha256 === "string" && <p className="break-all">문서 지문: {item.provenance.document_sha256} · 발급일 {typeof item.provenance.issued_at === "string" ? item.provenance.issued_at : "미확인"}</p>}
        </dd>}
        {!item.usable && <dd className="mt-1 text-xs text-amber-800">이전·미확인 값 — 현재 판단에 사용하지 않음</dd>}
        {item.reference_url && <dd><Link href={item.reference_url} className="mt-1 inline-block text-primary underline">저장된 분석 리포트 확인</Link></dd>}
      </div>)}</dl>
    </details>
    <div className="mt-3 space-y-1 text-xs leading-relaxed text-slate-500">{axis.limitations.map(item => <p key={item}>{item}</p>)}</div>
    <Link href={href} onClick={prepare} className="no-print mt-auto pt-4 text-sm font-semibold text-primary underline">{axis.review_label} →</Link>
  </section>;
}
