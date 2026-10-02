"use client";
import PropertyIdentityDetails from "@/components/PropertyIdentityDetails";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CaseDecisionSummary } from "@/lib/types";
import CandidateNextActions from "@/components/CandidateNextActions";
import DecisionAxisCard, { DecisionStatus } from "@/components/DecisionAxisCard";

const won = (value: number | null) => value === null ? "미확인" : `${value.toLocaleString("ko-KR")}원`;
const analysisLabels = { appraisal: "시세", simulation: "자금", rights: "권리" };
const statusLabels = { pending: "진행 중", completed: "완료", failed: "실패", stale: "갱신 필요" };
const inputLabels: Record<string, string> = {
  purchase_price: "매수가 (원)", loan_ratio: "대출 비율", annual_interest_rate: "연 금리 (%)", loan_years: "대출 기간 (년)",
  cash_available: "매수에 쓸 현금 (원)", monthly_payment_limit: "월 상환 한도 (원)", annual_income: "연소득 (원)",
  existing_loan_annual_payment: "기존 대출 연 상환액 (원)", owned_homes: "취득 후 주택 수 (이번 취득 포함)",
  adjusted_area: "조정대상지역", repayment_type: "상환 방식",
};
const repaymentLabels: Record<string, string> = { equal_payment: "원리금 균등", equal_principal: "원금 균등", interest_only: "만기 일시" };

export default function DecisionSummaryPage() {
  const caseId = Number(useParams<{ id: string }>().id);
  // 케이스를 바꾸면 이전 후보의 검토 결과가 잠깐 남지 않게 한다.
  return <DecisionSummary key={caseId} caseId={caseId} />;
}

function DecisionSummary({ caseId }: { caseId: number }) {
  const [data, setData] = useState<CaseDecisionSummary | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    async function load() {
      try {
        const value = await api.caseDecisionSummary(caseId, AbortSignal.any([abort.signal, AbortSignal.timeout(15000)]));
        if (!abort.signal.aborted) setData(value);
      } catch {
        if (!abort.signal.aborted) setError("요약을 불러오지 못했습니다. 로그인 상태와 연결을 확인한 뒤 새로고침해주세요.");
      }
    }
    void load();
    return () => abort.abort();
  }, [caseId]);
  const reload = async () => {
    const value = await api.caseDecisionSummary(caseId, AbortSignal.timeout(15000));
    setData(value); setError("");
  };

  return <div className="mx-auto max-w-6xl space-y-6">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <Link href={`/cases/${caseId}`} className="text-primary underline">← 후보 검토</Link>
      <button className="no-print rounded border px-3 py-2" onClick={() => window.print()}>인쇄 · PDF 저장</button>
    </div>
    <div><h1 className="text-3xl font-bold">매수 검토 요약</h1><p className="mt-2 text-slate-600">후보별 적합성·가격성·자금성·위험성·실행성을 근거와 함께 검토하세요.</p></div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {!data && !error && <p role="status">저장된 분석 결과를 불러오는 중…</p>}
    {data && <>
      <section className="space-y-2 rounded-xl border bg-white p-5">
        <h2 className="text-xl font-semibold">{data.case.title}</h2>
        <p>최대 예산 {won(data.case.budget_max)} · 후보 {data.decision.candidates.length}개</p>
        <p className="text-sm">선택 근거: {data.case.decision_reason || "아직 최종 후보를 선택하지 않았습니다."}</p>
        <p className="text-xs text-slate-500">검토 시각 {data.decision.evaluated_at} · 각 근거의 기준 시각은 아래에서 확인할 수 있습니다.</p>
      </section>
      <p className="rounded-xl bg-amber-50 p-4 text-sm leading-relaxed text-amber-950">{data.decision.boundary}</p>
      {data.decision.candidates.length > 0 && <section aria-label="후보별 판단 축 비교" className="overflow-x-auto rounded-xl border bg-white">
        <table className="w-full min-w-[680px] text-sm">
          <caption className="p-4 text-left text-lg font-bold">후보별 확인 상태</caption>
          <thead className="bg-slate-50"><tr><th scope="col" className="p-3 text-left">후보</th>{["적합성", "가격성", "자금성", "위험성", "실행성"].map(label => <th key={label} scope="col" className="p-3 text-left">{label}</th>)}</tr></thead>
          <tbody>{data.decision.candidates.map(candidate => <tr key={candidate.property_id} className="border-t">
            <th scope="row" className="p-3 text-left"><a href={`#decision-candidate-${candidate.property_id}`} className="text-primary underline">{candidate.name}</a>{candidate.status === "rejected" && <span className="ml-2 text-xs text-slate-500">제외</span>}</th>
            {candidate.axes.map(axis => <td key={axis.key} className="p-3"><DecisionStatus status={axis.status} /></td>)}
          </tr>)}</tbody>
        </table>
        <p className="p-4 text-xs text-slate-500">확인 상태는 등록된 자료의 검토 여부입니다. 추천 순위나 매수 안전성 점수가 아닙니다.</p>
      </section>}
      {data.decision.candidates.map(assessment => {
        const candidate = data.case.properties?.find(item => item.id === assessment.property_id);
        if (!candidate) return null;
        const selected = data.case.selected_property_id === candidate.id;
        const inputs = candidate.analyses.find(item => item.analysis_type === "simulation")?.summary.inputs;
        return <article key={candidate.id} id={`decision-candidate-${candidate.id}`} className="scroll-mt-20 space-y-5 rounded-2xl border bg-white p-5 sm:p-6">
          <div><h2 className="text-2xl font-bold">{candidate.name}</h2>
            {candidate.alias && <p className="mt-1 break-words text-sm text-primary">별칭: {candidate.alias}</p>}
            {candidate.address_details && <p className="mt-1 break-words text-sm text-slate-600">도로명: {candidate.address_details.road_address || "제공 정보 없음"} · 지번: {candidate.address_details.jibun_address}</p>}
            <PropertyIdentityDetails identity={candidate.identity} />
            <p className="mt-1 break-words text-slate-600">{candidate.address || "주소 미입력"}</p>
            <p className="mt-2 text-sm font-semibold text-primary">{candidate.status === "rejected" ? "제외 후보" : selected ? assessment.review_ready ? "사용자 선택 · 등록 검토 항목 확인" : "선호 후보 · 확인 필요" : assessment.review_ready ? "등록 검토 항목 확인 · 사용자 선택 대기" : "후보 검토 중"}</p>
          </div>
          {selected && !assessment.review_ready && <p className="rounded bg-amber-50 p-3 text-sm text-amber-900">이 후보는 선택됐지만 필수 검토가 끝나지 않았습니다. 아래 확인 사항을 해결한 뒤 거래 여부를 판단하세요.</p>}
          <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{([
            ["입력한 희망가", assessment.metrics.asking_price], ["필요 현금", assessment.metrics.required_cash],
            ["첫 달 대출 상환액", assessment.metrics.monthly_payment], ["희망가 − AVM 추정가", assessment.metrics.price_gap],
          ] as const).map(([label, value]) => <div key={label} className="rounded-lg bg-slate-50 p-3"><dt className="text-sm text-slate-500">{label}</dt><dd className="mt-1 break-words text-lg font-bold">{won(value)}</dd></div>)}</dl>
          <p className="text-sm text-slate-600">부족 현금: {won(assessment.metrics.cash_shortfall)} · 미확인·만료·변경된 분석은 현재 비교 금액에 사용하지 않습니다.</p>
          <div className="grid items-start gap-4 md:grid-cols-2 xl:grid-cols-3">{assessment.axes.map(axis => <DecisionAxisCard key={axis.key} axis={axis} property={candidate} caseId={caseId} profile={data.case.buyer_profile} />)}</div>
          <details className="text-sm">
            <summary className="cursor-pointer font-semibold">분석 기준일·유효기한</summary>
            <div className="mt-2 space-y-1 text-slate-600">{candidate.analyses.map(item => <p key={item.analysis_type}>{analysisLabels[item.analysis_type]}: {statusLabels[item.status]} · 분석일 {item.analyzed_at || "미확인"} · 유효기한 {item.expires_at || "미확인"}</p>)}{!candidate.analyses.length && <p>아직 저장된 분석이 없습니다.</p>}</div>
          </details>
          {inputs !== null && typeof inputs === "object" && !Array.isArray(inputs) && <details>
            <summary className="cursor-pointer text-sm font-semibold">자금 분석에 사용한 입력 조건</summary>
            <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(inputs).filter(([key, value]) => inputLabels[key] && value !== null && typeof value !== "object").map(([key, value]) => <div key={key}><dt className="text-slate-500">{inputLabels[key]}</dt><dd>{typeof value === "boolean" ? value ? "예" : "아니오" : repaymentLabels[String(value)] || String(value)}</dd></div>)}</dl>
          </details>}
          <CandidateNextActions property={{ ...candidate, next_actions: assessment.next_actions }} caseId={caseId} profile={data.case.buyer_profile} reload={reload} checklistBasePath={`/cases/${caseId}`} />
          <Link href={`/cases/${caseId}#candidate-checklist-${candidate.id}`} className="inline-block text-sm text-primary underline">후보 원본·체크리스트 확인</Link>
        </article>;
      })}
      {!data.decision.candidates.length && <p>관심 매물을 후보로 등록하면 다섯 판단 축과 다음 행동을 확인할 수 있습니다.</p>}
      <div className="no-print flex flex-wrap gap-3"><Link href={`/cases/${caseId}/comparison`} className="rounded bg-primary px-4 py-2 text-white">후보 비교·선택</Link><Link href="/listings" className="rounded border px-4 py-2 text-primary">관심 매물 등록</Link></div>
    </>}
  </div>;
}
