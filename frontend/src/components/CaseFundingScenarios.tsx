"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import type { CaseFundingScenarioResult } from "@/lib/types";

const won=(value:unknown)=>typeof value==="number"&&Number.isFinite(value)?`${Math.round(value/10000).toLocaleString()}만원`:"미확인";

export default function CaseFundingScenarios({caseId,propertyIds}:{caseId:number;propertyIds:number[]}) {
  const [result,setResult]=useState<CaseFundingScenarioResult|null>(null);
  const [loading,setLoading]=useState(false);const [error,setError]=useState("");
  const run=async(event:FormEvent<HTMLFormElement>)=>{
    event.preventDefault();if(loading)return;
    const values=new FormData(event.currentTarget);
    const price_delta_won=Number(values.get("price_delta_won")||0);
    const interest_delta_pct=Number(values.get("interest_delta_pct")||0);
    const reserve_delta_won=Number(values.get("reserve_delta_won")||0);
    if(!Number.isSafeInteger(price_delta_won)||!Number.isFinite(interest_delta_pct)||!Number.isSafeInteger(reserve_delta_won)){
      setError("변경할 금액과 금리를 확인해주세요.");return;
    }
    try{setLoading(true);setError("");setResult(await api.caseFundingScenarios(caseId,{property_ids:propertyIds,price_delta_won,interest_delta_pct,reserve_delta_won}));}
    catch{setError("자금 시나리오를 계산하지 못했습니다. 저장한 매수 조건과 후보 가격을 확인해주세요.");}
    finally{setLoading(false);}
  };
  return <section className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="font-bold">같은 조건으로 자금 시나리오 비교</h2>
    <p className="mt-1 text-sm text-slate-600">케이스에 저장한 매수 조건을 모든 후보에 적용합니다. 아래 변경값은 시험용이며 기존 분석·선택을 바꾸지 않습니다.</p>
    <form onSubmit={run} className="mt-3 grid gap-3 sm:grid-cols-4 sm:items-end">
      <label className="text-sm">매수가 변경 (원)<input name="price_delta_won" type="number" step="1" defaultValue="0" className="mt-1 w-full rounded border p-2" /></label>
      <label className="text-sm">금리 변경 (%p)<input name="interest_delta_pct" type="number" step="0.01" defaultValue="0" className="mt-1 w-full rounded border p-2" /></label>
      <label className="text-sm">비상자금 변경 (원)<input name="reserve_delta_won" type="number" step="1" defaultValue="0" className="mt-1 w-full rounded border p-2" /></label>
      <button disabled={loading||propertyIds.length===0} className="rounded bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{loading?"계산 중…":"후보 전체 비교"}</button>
    </form>
    {error&&<p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
    {result&&<div className="mt-4 space-y-3">{result.rows.map(row=><article key={row.property_id} className="rounded-lg border p-3 text-sm">
      <strong>{row.name}</strong>{row.source_status&&row.source_status!=="current"&&<span className="ml-2 text-amber-700">원본 매물 재확인 필요</span>}
      {row.baseline.status==="calculated"&&row.scenario.status==="calculated"?<div className="mt-2 grid gap-2 sm:grid-cols-3">
        <p>필요 현금<br /><b>{won(row.baseline.summary?.required_cash)} → {won(row.scenario.summary?.required_cash)}</b></p>
        <p>부족 자금<br /><b>{won(row.baseline.summary?.cash_shortfall)} → {won(row.scenario.summary?.cash_shortfall)}</b></p>
        <p>첫 달 상환액<br /><b>{won(row.baseline.summary?.monthly_payment)} → {won(row.scenario.summary?.monthly_payment)}</b></p>
        {(row.scenario.warnings??[]).length>0&&<p className="sm:col-span-3 text-amber-700">확인할 사항: {row.scenario.warnings?.join(" · ")}</p>}
      </div>:<p className="mt-2 text-amber-700">계산에 필요한 조건: {[...(row.baseline.missing??[]),...(row.scenario.missing??[])].filter((value,index,all)=>all.indexOf(value)===index).join(", ")||"입력 조건 확인"}</p>}
    </article>)}<p className="text-xs text-slate-500">참고용 계산이며 금융기관의 대출 승인 결과가 아닙니다. 조건 변경을 실제 분석에 적용하려면 각 후보에서 자금 분석을 다시 실행하세요.</p>
      <Link href={`/cases/${caseId}`} className="text-sm font-semibold text-primary underline">케이스 조건 수정</Link>
    </div>}
  </section>;
}
