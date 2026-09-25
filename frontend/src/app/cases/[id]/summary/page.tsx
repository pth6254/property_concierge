"use client";
import Link from "next/link";
import {useParams} from "next/navigation";
import {useEffect,useState} from "react";
import type {PurchaseCase,CaseCandidateComparison} from "@/lib/types";
import CandidateNextActions from "@/components/CandidateNextActions";

type Summary={case:PurchaseCase;comparison:CaseCandidateComparison};
const won=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?`${value.toLocaleString("ko-KR")}원`:"미확인";
const analysisLabels={appraisal:"시세",simulation:"자금",rights:"권리"};
const statusLabels={pending:"진행 중",completed:"완료",failed:"실패",stale:"갱신 필요"};
const inputLabels:Record<string,string>={purchase_price:"매수가 (원)",loan_ratio:"대출 비율",annual_interest_rate:"연 금리 (%)",loan_years:"대출 기간 (년)",cash_available:"보유 현금 (원)",monthly_payment_limit:"월 상환 한도 (원)",annual_income:"연소득 (원)",existing_loan_annual_payment:"기존 대출 연 상환액 (원)",owned_homes:"보유 주택 수",adjusted_area:"조정대상지역",repayment_type:"상환 방식"};

export default function DecisionSummaryPage(){
  const caseId=Number(useParams<{id:string}>().id);
  const [data,setData]=useState<Summary|null>(null);
  const [error,setError]=useState("");
  useEffect(()=>{
    const abort=new AbortController();
    async function load(){try{const res=await fetch(`/api/cases/${caseId}/summary`,{signal:AbortSignal.any([abort.signal,AbortSignal.timeout(15000)])});if(!res.ok)throw new Error("요약을 불러오지 못했습니다.");const value:Summary=await res.json();if(!abort.signal.aborted)setData(value);}catch(e){if(!abort.signal.aborted)setError(e instanceof Error?e.message:"조회 실패");}}
    void load();return()=>abort.abort();
  },[caseId]);
  const reload=async()=>{const res=await fetch(`/api/cases/${caseId}/summary`,{signal:AbortSignal.timeout(15000)});if(!res.ok)throw new Error("요약 갱신 실패");setData(await res.json());};
  return <div className="mx-auto max-w-6xl space-y-5">
    <div className="flex flex-wrap justify-between gap-3"><Link href={`/cases/${caseId}`} className="text-primary underline">← 후보 검토</Link><button className="no-print rounded border px-3 py-2" onClick={()=>window.print()}>인쇄 · PDF 저장</button></div>
    <h1 className="text-2xl font-bold">매수 검토 요약</h1>
    {error&&<p role="alert" className="text-red-700">{error}</p>}
    {!data&&!error&&<p>저장된 분석 결과를 불러오는 중…</p>}
    {data&&<><p className="text-lg font-semibold">{data.case.title} · 최대 예산 {won(data.case.budget_max)}</p><p>선택 근거: {data.case.decision_reason||"아직 최종 후보를 선택하지 않았습니다."}</p>
    <p className="rounded bg-amber-50 p-3 text-sm">저장된 자료에 따른 참고용 요약입니다. AVM은 법정 감정평가가 아니며, 대출 승인·매물 존재·거래 안전성을 보장하지 않습니다.</p>
    {data.comparison.rows.map(row=>{const candidate=data.case.properties?.find(p=>p.id===row.property_id);if(!candidate)return null;const funding=candidate.analyses.find(a=>a.analysis_type==="simulation");const inputs=funding?.summary.inputs;const usableFunding=funding?.status==="completed"&&(!funding.summary.purchase_price||funding.summary.purchase_price===candidate.asking_price);
      return <article key={row.property_id} className="break-inside-avoid space-y-4 rounded-xl border bg-white p-5">
        <h2 className="text-xl font-bold">{row.name} {data.case.selected_property_id===row.property_id&&<span className="text-sm text-primary">최종 선택</span>}{row.status==="rejected"&&<span className="text-sm text-slate-500"> 제외 후보</span>}</h2><p>{row.address}</p>
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{[["확인한 희망가",won(row.asking_price)],["필요 현금",usableFunding?won(funding?.summary.required_cash):"분석·갱신 필요"],["첫 달 대출 상환액",usableFunding?won(funding?.summary.monthly_payment):"분석·갱신 필요"],["희망가 − AVM 추정가",won(row.price_gap)]].map(([label,value])=><div key={label} className="rounded bg-slate-50 p-3"><dt className="text-xs text-slate-500">{label}</dt><dd className="mt-1 font-bold">{value}</dd></div>)}</dl>
        <p className="text-sm">부족 현금: {usableFunding?won(funding?.summary.cash_shortfall):"미확인"} · 시세 차이는 유효한 분석과 신뢰도 기준을 충족할 때만 표시합니다.</p>
        {!!row.warnings.length&&<ul className="list-inside list-disc rounded bg-amber-50 p-3 text-sm text-amber-900">{row.warnings.map(w=><li key={w}>{w}</li>)}</ul>}
        <div className="space-y-1 text-xs text-slate-600">{candidate.analyses.map(a=><p key={a.analysis_type}>{analysisLabels[a.analysis_type]}: {statusLabels[a.status]} · 분석일 {a.analyzed_at||"미확인"} · 유효기한 {a.expires_at||"미확인"}</p>)}{!candidate.analyses.length&&<p>아직 저장된 분석이 없습니다.</p>}</div>
        {inputs!==null&&typeof inputs==="object"&&<details><summary className="cursor-pointer text-sm">자금 분석에 사용한 입력 조건</summary><dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2">{Object.entries(inputs).filter(([k,v])=>inputLabels[k]&&v!==null&&typeof v!=="object").map(([key,value])=><div key={key}><dt className="text-slate-500">{inputLabels[key]}</dt><dd>{typeof value==="boolean"?(value?"예":"아니오"):({equal_payment:"원리금 균등",equal_principal:"원금 균등",interest_only:"만기 일시"} as Record<string,string>)[String(value)]||String(value)}</dd></div>)}</dl></details>}
        <CandidateNextActions property={candidate} caseId={caseId} reload={reload} checklistBasePath={`/cases/${caseId}`}/>
        <Link href={`/cases/${caseId}#candidate-checklist-${candidate.id}`} className="inline-block text-sm text-primary underline">후보 원본·체크리스트 확인</Link>
      </article>;
    })}
    {!data.comparison.rows.length&&<p>후보를 등록하면 분석·자금·위험 요약을 볼 수 있습니다.</p>}
    <Link href={`/cases/${caseId}/comparison`} className="inline-block rounded bg-primary px-4 py-2 text-white">후보 비교·선택</Link></>}
  </div>;
}
