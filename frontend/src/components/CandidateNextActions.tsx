"use client";

import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { setSessionValue } from "@/lib/sessionStore";
import type { CaseProperty } from "@/lib/types";

export default function CandidateNextActions({ property, caseId, reload, checklistBasePath = "" }: {
  property: CaseProperty; caseId: number; reload: () => Promise<void>; checklistBasePath?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [price, setPrice] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const actions = property.next_actions;
  const editPrice = () => {
    setPrice(property.asking_price == null ? "" : String(property.asking_price));
    setError(""); setEditing(true);
  };
  const savePrice = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = Number(price);
    if (!price.trim() || !Number.isSafeInteger(value) || value < 0) {
      setError("희망가를 0 이상의 정수(원)로 입력해주세요."); return;
    }
    setSaving(true); setError("");
    try {
      await api.updateCaseProperty(caseId, property.id, { asking_price: value });
      await reload(); setEditing(false);
    } catch { setError("희망가를 저장하지 못했습니다. 다시 시도해주세요."); }
    finally { setSaving(false); }
  };
  const prepare = (target: string) => {
    if (target === "simulation") setSessionValue("simFromListing", JSON.stringify({
      asking_price: property.asking_price, property_type: property.category,
      inputs: property.analyses.find(analysis => analysis.analysis_type === "simulation")?.summary.inputs,
      case_id: caseId, candidate_id: property.id,
    }));
    if (target === "rights") setSessionValue("rightsCandidate", JSON.stringify({
      market_price: property.appraisal?.estimated_value ?? property.asking_price,
      address: property.address, case_id: caseId, candidate_id: property.id,
    }));
  };

  return <section className="mt-4 rounded-lg border border-slate-200 bg-slate-50 p-4" aria-label={`${property.name} 다음 행동`}>
    <div className="flex items-center justify-between gap-3">
      <h4 className="text-sm font-semibold">다음 행동{property.status !== "rejected" && actions && actions.length > 0 ? ` · ${actions.length}개` : ""}</h4>
      <button type="button" onClick={editPrice} className="text-xs font-semibold text-primary hover:underline">희망가 수정</button>
    </div>
    {editing && <form onSubmit={savePrice} className="mt-3 flex flex-wrap items-end gap-2">
      <label className="text-xs">희망가(원)<input autoFocus required type="number" min="0" step="1" value={price} onChange={(event) => setPrice(event.target.value)} className="mt-1 block rounded border bg-white px-3 py-2" /></label>
      <button disabled={saving} className="rounded bg-primary px-3 py-2 text-xs font-semibold text-white disabled:opacity-50">저장</button>
      <button type="button" disabled={saving} onClick={() => setEditing(false)} className="rounded border px-3 py-2 text-xs">취소</button>
    </form>}
    {error && <p role="alert" className="mt-2 text-xs text-red-600">{error}</p>}
    {property.status === "rejected" ? <p className="mt-2 text-xs text-slate-500">제외한 후보입니다. 검토를 재개하면 다음 행동을 안내합니다.</p> : actions && actions.length > 0 ?
      <ul className="mt-3 space-y-3">{actions.map((action) => {
        const href = action.target === "appraisal" ? `/appraisal?caseId=${caseId}&candidateId=${property.id}`
          : action.target === "checklist" ? `${checklistBasePath}#candidate-checklist-${property.id}` : `/${action.target}`;
        const buttonClass = "shrink-0 rounded border bg-white px-3 py-2 text-xs font-semibold text-primary hover:border-emerald-300";
        return <li key={action.code} className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0 flex-1"><p className={`text-xs font-semibold ${action.priority === "warning" ? "text-amber-800" : "text-slate-800"}`}>{action.title}</p><p className="mt-1 text-xs text-slate-500">{action.reason}</p></div>
          {action.target === "price" ? <button type="button" onClick={editPrice} className={buttonClass}>가격 입력</button> : <Link href={href} onClick={() => prepare(action.target)} className={buttonClass}>{action.target === "checklist" ? "검토 항목 보기" : "분석으로 이동"}</Link>}
        </li>;
      })}</ul> : actions ? <div className="mt-3 text-xs text-slate-600">
        <p>현재 등록된 정보에서 남은 확인 항목이 없습니다. 매수 안전성을 보장하는 판단은 아닙니다.</p>
        <Link href={`/cases/${caseId}/${property.status === "selected" ? "execution" : "comparison"}`} className="mt-2 inline-block font-semibold text-primary hover:underline">{property.status === "selected" ? "실행 계획 확인" : "후보 비교·선택으로 이동"}</Link>
      </div> : <p className="mt-2 text-xs text-slate-500">다음 행동 정보를 불러오지 못했습니다.</p>}
  </section>;
}
