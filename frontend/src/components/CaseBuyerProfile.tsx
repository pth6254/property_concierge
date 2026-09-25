"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { BuyerProfile } from "@/lib/types";

const NUMBER_FIELDS = [
  ["cash_available", "보유 현금 (원)"], ["emergency_reserve", "제외할 비상자금 (원)"],
  ["monthly_payment_limit", "월 상환 한도 (원)"], ["annual_income", "연소득 (원)"],
  ["existing_loan_annual_payment", "기존 대출 연간 상환액 (원)"],
  ["loan_ratio", "대출 비율 (0~0.9)"], ["annual_interest_rate", "가정 금리 (%)"],
  ["loan_years", "대출 기간 (년)"], ["owned_homes", "취득 후 주택 수"],
  ["min_area_sqm", "최소 면적 (㎡)"], ["min_build_year", "최소 준공 연도"],
] as const;
type NumberField = (typeof NUMBER_FIELDS)[number][0];
const TYPES = [
  ["apartment", "아파트"], ["officetel", "오피스텔"],
  ["row_house", "연립·다세대"], ["detached", "단독·다가구"],
  ["non_residential", "상업·업무"], ["industrial", "산업용"], ["land", "토지"],
] as const;

export default function CaseBuyerProfile({ caseId, profile, budgetMax, onSaved }: { caseId: number; profile: BuyerProfile; budgetMax: number | null; onSaved: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    const values = new FormData(event.currentTarget);
    const next: BuyerProfile = { ...profile };
    for (const [key, label] of NUMBER_FIELDS) {
      const raw = String(values.get(key) ?? "").trim();
      const parsed = raw ? Number(raw) : null;
      if (parsed !== null && (!Number.isFinite(parsed) || parsed < 0)) {
        setMessage(`${label} 입력값을 확인해주세요.`);
        return;
      }
      // 숫자 필드만 순회하므로 동적 키의 타입을 여기에서 제한한다.
      (next as unknown as Record<NumberField, number | null>)[key] = parsed;
    }
    next.emergency_reserve ??= 0;
    next.existing_loan_annual_payment ??= 0;
    next.adjusted_area = values.get("adjusted_area") === "on";
    next.priority = String(values.get("priority")) as BuyerProfile["priority"];
    next.property_types = values.getAll("property_types").map(String);
    const budgetRaw = String(values.get("budget_max") ?? "").trim();
    const budget_max = budgetRaw ? Number(budgetRaw) : null;
    if (budget_max !== null && (!Number.isSafeInteger(budget_max) || budget_max < 0)) {
      setMessage("최대 예산을 원 단위의 정수로 입력해주세요.");
      return;
    }
    try {
      setBusy(true);
      setMessage("");
      await api.updateCase(caseId, { buyer_profile: next, budget_max });
      await onSaved();
      setMessage("매수 조건을 저장했습니다. 후보 시나리오와 추천에 적용됩니다.");
    } catch {
      setMessage("매수 조건을 저장하지 못했습니다. 비상자금·금리·대출 비율을 확인해주세요.");
    } finally { setBusy(false); }
  };
  return <details className="rounded-xl border bg-white p-4">
    <summary className="cursor-pointer font-bold">공통 매수 조건</summary>
    <p className="mt-2 text-sm text-slate-600">같은 케이스의 후보에 공통으로 적용됩니다. 자금 비교에서는 보유 현금에서 비상자금을 제외합니다.</p>
    <form onSubmit={submit} className="mt-4 space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">최대 예산 (원)<input name="budget_max" type="number" min="0" step="1" defaultValue={budgetMax ?? ""} className="mt-1 w-full rounded border p-2" /></label>
        {NUMBER_FIELDS.map(([key, label]) => <label key={key} className="text-sm">{label}<input name={key} type="number" min="0" step={["loan_ratio", "annual_interest_rate", "min_area_sqm"].includes(key) ? "0.01" : "1"} defaultValue={profile[key] ?? ""} className="mt-1 w-full rounded border p-2" /></label>)}
        <label className="text-sm">가장 중요한 기준<select name="priority" defaultValue={profile.priority ?? "cash"} className="mt-1 w-full rounded border p-2"><option value="cash">필요 현금</option><option value="monthly">월 상환 부담</option><option value="value">가격 수준</option><option value="liquidity">거래량</option><option value="age">연식</option></select></label>
        <label className="flex items-center gap-2 text-sm"><input name="adjusted_area" type="checkbox" defaultChecked={profile.adjusted_area ?? false} />조정대상지역으로 가정</label>
      </div>
      <fieldset><legend className="text-sm font-medium">관심 물건 유형 (선택하지 않으면 모두)</legend><div className="mt-2 flex flex-wrap gap-3">{TYPES.map(([value, label]) => <label key={value} className="flex items-center gap-1 text-sm"><input name="property_types" value={value} type="checkbox" defaultChecked={(profile.property_types ?? []).includes(value)} />{label}</label>)}</div></fieldset>
      <button disabled={busy} className="rounded bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{busy ? "저장 중…" : "매수 조건 저장"}</button>
    </form>
    {message && <p role="status" className="mt-2 text-sm">{message}</p>}
  </details>;
}
