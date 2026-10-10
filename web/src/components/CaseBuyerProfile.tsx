"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import type { BuyerProfile } from "@/lib/types";
import MoneyInput, { wonFromInput } from "@/components/MoneyInput";
import { formatWonKorean } from "@/lib/moneyInput";

// 금액 칸은 다른 화면과 같은 MoneyInput 규칙(숫자만 = 원, 억·만 허용)을 쓴다.
const MONEY_FIELDS = [
  ["cash_available", "보유 현금"], ["emergency_reserve", "제외할 비상자금"],
  ["monthly_payment_limit", "월 상환 한도"], ["annual_income", "연소득"],
  ["existing_loan_annual_payment", "기존 대출 연간 상환액"],
] as const;
type MoneyField = (typeof MONEY_FIELDS)[number][0];

const NUMBER_FIELDS = [
  ["loan_ratio", "대출 비율 (0~0.9)"], ["annual_interest_rate", "가정 금리 (%)"],
  ["loan_years", "대출 기간 (년)"], ["owned_homes", "취득 후 주택 수"],
  ["min_area_sqm", "최소 면적 (㎡)"], ["min_build_year", "최소 준공 연도"],
  ["max_area_sqm", "최대 면적 (㎡)"], ["max_build_year", "최대 준공 연도"],
  ["market_months", "실거래 조회 기간 (개월)"],
] as const;
type NumberField = (typeof NUMBER_FIELDS)[number][0];
const TYPES = [
  ["apartment", "아파트"], ["officetel", "오피스텔"],
  ["row_house", "연립·다세대"], ["detached", "단독·다가구"],
  ["non_residential", "상업·업무"], ["industrial", "산업용"], ["land", "토지"],
] as const;

export default function CaseBuyerProfile({ caseId, profile, budgetMax, onSaved, onSaving }: { caseId: number; profile: BuyerProfile; budgetMax: number | null; onSaved: () => Promise<void>; onSaving: () => void }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [money, setMoney] = useState<Record<MoneyField | "budget_max", string>>(() => ({
    budget_max: budgetMax == null ? "" : String(budgetMax),
    ...Object.fromEntries(MONEY_FIELDS.map(([key]) => [key, profile[key] == null ? "" : String(profile[key])])) as Record<MoneyField, string>,
  }));
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy) return;
    onSaving();
    const values = new FormData(event.currentTarget);
    const next: BuyerProfile = { ...profile };
    for (const [key, label] of NUMBER_FIELDS) {
      const raw = String(values.get(key) ?? "").trim();
      const parsed = raw ? Number(raw) : null;
      if (parsed !== null && (!Number.isFinite(parsed) || parsed < 0)) {
        setMessage(`${label} 입력값을 확인해주세요.`);
        return;
      }
      if (key === "owned_homes" && parsed !== null && (!Number.isInteger(parsed) || parsed < 1 || parsed > 100)) {
        setMessage("취득 후 주택 수는 1~100의 정수로 입력해주세요. 첫 주택 취득은 1입니다.");
        return;
      }
      // 숫자 필드만 순회하므로 동적 키의 타입을 여기에서 제한한다.
      (next as unknown as Record<NumberField, number | null>)[key] = parsed;
    }
    let budget_max: number | null;
    try {
      // 비상자금·기존 상환액은 비어 있으면 아래에서 0으로 채운다(기존 규칙과 동일).
      for (const [key, label] of MONEY_FIELDS) (next as unknown as Record<MoneyField, number | null>)[key] = wonFromInput(money[key], label) ?? null;
      budget_max = wonFromInput(money.budget_max, "최대 예산") ?? null;
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "금액 입력값을 확인해주세요.");
      return;
    }
    next.emergency_reserve ??= 0;
    next.existing_loan_annual_payment ??= 0;
    next.market_months ??= 12;
    next.adjusted_area = values.get("adjusted_area") === "on";
    next.priority = String(values.get("priority")) as BuyerProfile["priority"];
    next.property_types = values.getAll("property_types").map(String);
    try {
      setBusy(true);
      setMessage("");
      await api.updateCase(caseId, { buyer_profile: next, budget_max });
      await onSaved();
    } catch {
      setMessage("매수 조건을 저장하지 못했습니다. 비상자금·금리·대출 비율을 확인해주세요.");
    } finally { setBusy(false); }
  };
  const summary = [budgetMax ? `예산 ${formatWonKorean(budgetMax)}` : "예산 미입력",
    profile.cash_available != null ? `보유 현금 ${formatWonKorean(profile.cash_available)}` : "보유 현금 미입력",
    profile.monthly_payment_limit != null ? `월 상환 한도 ${formatWonKorean(profile.monthly_payment_limit)}` : "월 상환 한도 미입력",
    profile.owned_homes != null ? `취득 후 ${profile.owned_homes}주택` : "주택 수 미입력"].join(" · ");
  // 저장된 조건이 있으면 접어서 한 줄 요약만 보여준다. 후보 목록이 화면 위쪽에 오도록 하기 위함이다.
  return <details open={!profile.cash_available || !budgetMax} className="rounded-xl border bg-white p-4">
    <summary className="cursor-pointer"><span className="font-bold">공통 매수 조건</span><span className="ml-2 text-xs text-slate-500">{summary}</span></summary>
    <p className="mt-2 text-sm text-slate-600">같은 케이스의 후보에 공통으로 적용됩니다. 자금 비교에서는 보유 현금에서 비상자금을 제외합니다.</p>
    <p className="mt-1 text-xs text-slate-500">주택 수는 이번 취득을 포함한 취득 후 기준입니다. 무주택자가 첫 주택을 취득하면 1, 기존 1주택을 유지하면서 추가 취득하면 2를 입력하세요.</p>
    <form onSubmit={submit} className="mt-4 space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <label className="text-sm">최대 예산<MoneyInput aria-label="최대 예산" placeholder="예: 9억" smallWarningBelow={10_000_000} value={money.budget_max} onChange={value => setMoney(current => ({ ...current, budget_max: value }))} className="mt-1 w-full rounded border p-2" /></label>
        {MONEY_FIELDS.map(([key, label]) => <label key={key} className="text-sm">{label}<MoneyInput aria-label={label} placeholder={key === "monthly_payment_limit" ? "예: 200만" : "예: 3억"} value={money[key]} onChange={value => setMoney(current => ({ ...current, [key]: value }))} className="mt-1 w-full rounded border p-2" /></label>)}
        {NUMBER_FIELDS.map(([key, label]) => <label key={key} className="text-sm">{label}<input name={key} type="number" min={["owned_homes", "loan_years", "market_months"].includes(key) ? "1" : "0"} max={key === "owned_homes" ? 100 : key === "loan_years" ? 50 : undefined} step={["loan_ratio", "annual_interest_rate", "min_area_sqm", "max_area_sqm"].includes(key) ? "0.01" : "1"} defaultValue={profile[key] ?? ""} className="mt-1 w-full rounded border p-2" /></label>)}
        <label className="text-sm">가장 중요한 기준<select name="priority" defaultValue={profile.priority ?? "cash"} className="mt-1 w-full rounded border p-2"><option value="cash">필요 현금</option><option value="monthly">월 상환 부담</option><option value="value">가격 수준</option><option value="liquidity">거래량</option><option value="age">연식</option></select></label>
        <label className="flex items-center gap-2 text-sm"><input name="adjusted_area" type="checkbox" defaultChecked={profile.adjusted_area ?? false} />조정대상지역으로 가정</label>
      </div>
      <fieldset><legend className="text-sm font-medium">관심 물건 유형 (선택하지 않으면 모두)</legend><div className="mt-2 flex flex-wrap gap-3">{TYPES.map(([value, label]) => <label key={value} className="flex items-center gap-1 text-sm"><input name="property_types" value={value} type="checkbox" defaultChecked={(profile.property_types ?? []).includes(value)} />{label}</label>)}</div></fieldset>
      <button disabled={busy} className="rounded bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">{busy ? "저장 중…" : "매수 조건 저장"}</button>
    </form>
    {message && <p role="status" className="mt-2 text-sm">{message}</p>}
  </details>;
}
