"use client";

import { useState } from "react";
import ExternalListingLink from "@/components/ExternalListingLink";
import ComplexAddressDetails from "@/components/ComplexAddressDetails";
import type { ConciergeComplex } from "@/lib/types";
import MoneyInput from "@/components/MoneyInput";
import { parseWon } from "@/lib/moneyInput";

export type ComplexCandidateInput = { name: string; address: string; area_sqm: number; asking_price?: number };

export default function ConciergeComplexCard({ item, region, disabled, onSave, caseId, saved = false, saveLabel = "후보 저장·선택" }: {
  item: ConciergeComplex; region: string; disabled: boolean;
  caseId?: string; saved?: boolean; saveLabel?: string;
  onSave: (input: ComplexCandidateInput) => Promise<void>;
}) {
  const [address, setAddress] = useState(item.road_address || item.jibun_address || (region.endsWith(` ${item.dong}`) ? region : `${region} ${item.dong}`));
  const [area, setArea] = useState("");
  const [price, setPrice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const save = async () => {
    if (disabled || saving) return;
    const sqm = Number(area);
    // 다른 화면과 같은 금액 규칙(숫자만 = 원, 억·만 허용)을 쓴다. 이전에는 이 칸만 만원 숫자였다.
    const won = price.trim() ? parseWon(price) : undefined;
    if (!address.trim() || !Number.isFinite(sqm) || sqm <= 0 || (won !== undefined && (!Number.isSafeInteger(won) || won <= 0))) {
      setError("주소와 실제 검토할 전용면적을 입력해주세요. 희망가는 양수로 입력하거나 비워둘 수 있습니다."); return;
    }
    setSaving(true); setError("");
    try { await onSave({ name: item.complex_name, address: address.trim(), area_sqm: sqm, asking_price: won }); }
    catch { setError("후보를 저장하지 못했습니다. 다시 시도해주세요."); }
    finally { setSaving(false); }
  };
  return <article aria-label={`${item.complex_name} 후보 저장`} className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
    <strong className="block text-sm">{item.complex_name}</strong>
    <p className="text-xs text-slate-500">{region.endsWith(` ${item.dong}`) ? region : `${region} ${item.dong}`}</p>
    <ComplexAddressDetails item={item} />
    <ExternalListingLink context={{ name: item.complex_name, address, propertyType: "apartment", caseId }} compact />
    <p className="text-slate-500">실거래 시점수정 평균 {item.avg_price.toLocaleString()}만원 · 평균 면적 {item.avg_area_m2}㎡</p>
    <p className="text-xs text-slate-500">단지의 실거래 집계입니다. 현재 매물 호가·실제 검토 면적은 별도로 확인하세요.</p>
    {item.funding_preview && <div className="rounded-lg bg-emerald-50 p-3 text-xs leading-5">
      <strong>내 자금 기준 참고 계산</strong>
      {item.funding_preview.status === "calculated" ? <>
        <p>예상 필요 현금 {(item.funding_preview.summary?.required_cash ?? 0).toLocaleString()}원 · 월 상환액 {(item.funding_preview.summary?.monthly_payment ?? 0).toLocaleString()}원</p>
        {(item.funding_preview.warnings ?? []).map(warning => <p key={warning} className="text-amber-800">{warning}</p>)}
      </> : item.funding_preview.status === "needs_input" ? <p>공통 매수 조건의 현금·상환 한도·금리·대출 비율·주택 수를 입력하면 비교할 수 있습니다.</p> : <p>자금 계산을 완료하지 못했습니다. 공통 매수 조건을 확인한 뒤 다시 조회해주세요.</p>}
      <p className="text-slate-500">{item.funding_preview.basis}</p>
    </div>}
    <button type="button" aria-expanded={open} onClick={()=>setOpen(!open)} disabled={saved} className="text-sm font-semibold text-primary underline disabled:text-slate-400">{saved ? "이 케이스에 후보 저장됨" : open ? "직접 입력 닫기" : "매물 링크 없이 후보 직접 입력"}</button>
    {open && <div className="space-y-3 border-t border-slate-100 pt-3">
    <label className="block">검토 주소<input value={address} onChange={(e) => setAddress(e.target.value)} disabled={disabled || saving} className="mt-1 w-full rounded border border-slate-300 p-2" /></label>
    <label className="block">실제 검토 전용면적 (㎡)<input type="number" min="0.01" step="any" value={area} onChange={(e) => setArea(e.target.value)} disabled={disabled || saving} placeholder="검토할 주택의 면적 입력" className="mt-1 w-full rounded border p-2" /></label>
    <label className="block">확인한 희망가 (선택)<MoneyInput aria-label="확인한 희망가 (선택)" value={price} onChange={setPrice} disabled={disabled || saving} smallWarningBelow={10_000_000} placeholder="예: 8억 · 평균 실거래가는 자동 입력하지 않습니다" className="mt-1 w-full rounded border p-2" /></label>
    <p className="text-slate-500">주소·면적을 확인해 저장하세요. 자금 분석에는 실제 희망가가 필요합니다.</p>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    <button type="button" onClick={save} disabled={disabled || saving} className="rounded bg-primary px-3 py-2 text-white disabled:opacity-40">{saving ? "저장 중…" : saveLabel}</button>
    </div>}
  </article>;
}
