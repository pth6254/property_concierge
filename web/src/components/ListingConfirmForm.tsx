"use client";
import { useState, type FormEvent } from "react";
import MoneyInput, { wonFromInput } from "@/components/MoneyInput";
import { listingApi, type ImportedListing } from "@/lib/listings";

const STATUS_OPTIONS = [["active", "거래 가능"], ["withdrawn", "철회"], ["completed", "거래 완료"], ["unknown", "상태 미확인"]] as const;

// datetime-local 입력은 기기 시간대 기준이다. 저장 시 시간대가 포함된 ISO로 바꾼다.
function localNow(): string {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

/**
 * 원본을 다시 확인한 결과(확인 시각·거래 상태·가격)만 저장한다.
 * 이름·주소·면적·동호는 바꾸지 않는다. 물건이 다르면 새 매물로 등록한다. 이전 값은 변경 이력에 남는다.
 */
export default function ListingConfirmForm({ item, onSaved, onCancel }: {
  item: ImportedListing; onSaved: (updated: ImportedListing) => void; onCancel: () => void;
}) {
  // 입력은 분 단위라 기본값을 그대로 저장하면 같은 분 안의 직전 저장보다 이른 시각이 될 수 있다. 기본값이면 실제 현재 시각을 쓴다.
  const [initialAt] = useState(localNow);
  const [confirmedAt, setConfirmedAt] = useState(initialAt);
  const [status, setStatus] = useState(item.status);
  const [asking, setAsking] = useState(item.asking_price == null ? "" : String(item.asking_price));
  const [deposit, setDeposit] = useState(item.deposit == null ? "" : String(item.deposit));
  const [rent, setRent] = useState(item.monthly_rent == null ? "" : String(item.monthly_rent));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (busy) return;
    setError("");
    try {
      const checked = confirmedAt === initialAt ? new Date() : new Date(confirmedAt);
      if (!Number.isFinite(checked.getTime())) throw new Error("확인 일시를 입력해주세요.");
      const body = item.transaction_type === "purchase" ? { asking_price: wonFromInput(asking, "희망가") }
        : item.transaction_type === "lease" ? { deposit: wonFromInput(deposit, "보증금") }
        : { deposit: wonFromInput(deposit, "보증금"), monthly_rent: wonFromInput(rent, "월세") };
      setBusy(true);
      onSaved(await listingApi.confirm(item.id, { confirmed_at: checked.toISOString(), status, ...body }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "다시 확인한 내용을 저장하지 못했습니다."); }
    finally { setBusy(false); }
  };
  return <form onSubmit={submit} aria-label={`${item.name} 다시 확인`} className="space-y-3 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
    <p className="text-xs text-slate-600">제공자나 원문에서 지금 확인한 상태와 가격을 저장합니다. 이름·주소·면적·동호는 바뀌지 않으며, 이전 값은 변경 이력에 남습니다.</p>
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="block">확인 일시 (현재 기기 시간대)<input type="datetime-local" required value={confirmedAt} max={localNow()} onChange={event => setConfirmedAt(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 bg-white p-2" /></label>
      <label className="block">거래 상태<select aria-label="거래 상태" value={status} onChange={event => setStatus(event.target.value)} className="mt-1 block w-full rounded border border-slate-300 bg-white p-2">{STATUS_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      {item.transaction_type === "purchase" && <label className="block">확인한 희망가<MoneyInput aria-label="확인한 희망가" required value={asking} onChange={setAsking} smallWarningBelow={10_000_000} placeholder="예: 8억" className="mt-1 w-full rounded border border-slate-300 bg-white p-2" /></label>}
      {item.transaction_type !== "purchase" && <label className="block">확인한 보증금<MoneyInput aria-label="확인한 보증금" required value={deposit} onChange={setDeposit} placeholder="예: 3억" className="mt-1 w-full rounded border border-slate-300 bg-white p-2" /></label>}
      {item.transaction_type === "rent" && <label className="block">확인한 월세<MoneyInput aria-label="확인한 월세" required value={rent} onChange={setRent} placeholder="예: 150만" className="mt-1 w-full rounded border border-slate-300 bg-white p-2" /></label>}
    </div>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    <div className="flex gap-2">
      <button disabled={busy} className="rounded bg-primary px-3 py-1.5 font-semibold text-white disabled:opacity-50">{busy ? "저장 중…" : "확인 내용 저장"}</button>
      <button type="button" disabled={busy} onClick={onCancel} className="rounded border border-slate-300 bg-white px-3 py-1.5">취소</button>
    </div>
  </form>;
}
