"use client";

import { useState } from "react";
import ExternalListingLink from "@/components/ExternalListingLink";
import type { ConciergeComplex } from "@/lib/types";

export type ComplexCandidateInput = { name: string; address: string; area_sqm: number; asking_price?: number };

export default function ConciergeComplexCard({ item, region, disabled, onSave }: {
  item: ConciergeComplex; region: string; disabled: boolean;
  onSave: (input: ComplexCandidateInput) => Promise<void>;
}) {
  const [address, setAddress] = useState(region.endsWith(` ${item.dong}`) ? region : `${region} ${item.dong}`);
  const [area, setArea] = useState("");
  const [price, setPrice] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const save = async () => {
    if (disabled || saving) return;
    const sqm = Number(area);
    const won = price ? Math.round(Number(price) * 10000) : undefined;
    if (!address.trim() || !Number.isFinite(sqm) || sqm <= 0 || (won !== undefined && (!Number.isSafeInteger(won) || won <= 0))) {
      setError("주소와 실제 검토할 전용면적을 입력해주세요. 희망가는 양수로 입력하거나 비워둘 수 있습니다."); return;
    }
    setSaving(true); setError("");
    try { await onSave({ name: item.complex_name, address: address.trim(), area_sqm: sqm, asking_price: won }); }
    catch { setError("후보를 저장하지 못했습니다. 다시 시도해주세요."); }
    finally { setSaving(false); }
  };
  return <article aria-label={`${item.complex_name} 후보 저장`} className="mt-3 space-y-2 rounded-xl border border-emerald-200 p-3 text-xs">
    <strong className="block text-sm">{item.complex_name}</strong>
    <ExternalListingLink query={`${region} ${item.complex_name}`} />
    <p className="text-slate-500">실거래 시점수정 평균 {item.avg_price.toLocaleString()}만원 · 평균 면적 {item.avg_area_m2}㎡</p>
    <label className="block">검토 주소<input value={address} onChange={(e) => setAddress(e.target.value)} disabled={disabled || saving} className="mt-1 w-full rounded border p-2" /></label>
    <label className="block">실제 검토 전용면적 (㎡)<input type="number" min="0.01" step="any" value={area} onChange={(e) => setArea(e.target.value)} disabled={disabled || saving} placeholder="검토할 주택의 면적 입력" className="mt-1 w-full rounded border p-2" /></label>
    <label className="block">확인한 희망가 (만원, 선택)<input type="number" min="1" step="any" value={price} onChange={(e) => setPrice(e.target.value)} disabled={disabled || saving} placeholder="평균 실거래가는 자동 입력하지 않습니다" className="mt-1 w-full rounded border p-2" /></label>
    <p className="text-slate-500">주소·면적을 확인해 저장하세요. 자금 분석에는 실제 희망가가 필요합니다.</p>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    <button type="button" onClick={save} disabled={disabled || saving} className="rounded bg-primary px-3 py-2 text-white disabled:opacity-40">{saving ? "저장 중…" : "후보 저장·선택"}</button>
  </article>;
}
