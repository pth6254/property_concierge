"use client";

import { useRef, useState, type FormEvent } from "react";
import { listingApi, type ListingObservation } from "@/lib/listings";
import ListingCollector from "@/components/ListingCollector";
import type { ListingEntryContext } from "@/lib/listingNavigation";

export default function ListingLinkForm({ onSaved, onRegistered, initialValues = {} }: { onSaved: () => void; onRegistered?: () => void; initialValues?: ListingEntryContext }) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [transaction, setTransaction] = useState("purchase");
  const [seed, setSeed] = useState<(Pick<ListingObservation, "source_url" | "fields"> & { observation_id?: number }) | null>(null);
  const lock = useRef(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (lock.current) return;
    const form = event.currentTarget; const data = new FormData(form);
    const value = (key: string) => String(data.get(key) ?? "").trim();
    try {
      const url = new URL(value("source_url"));
      if (url.protocol !== "https:" || !["land.naver.com", "new.land.naver.com", "fin.land.naver.com", "m.land.naver.com"].includes(url.hostname) || url.username || url.password || url.port) throw Error("네이버페이 부동산의 HTTPS 매물 링크를 입력해주세요.");
      const articleId = url.pathname.match(/^\/articles\/(\d+)\/?$/)?.[1] ?? url.searchParams.get("articleNo");
      if (!articleId || !/^\d{1,30}$/.test(articleId)) throw Error("검색 화면 대신 개별 매물 링크를 입력해주세요. 매물 번호가 있는 링크가 필요합니다.");
      const confirmed = new Date(value("confirmed_at"));
      if (!Number.isFinite(confirmed.getTime())) throw Error("확인 일시를 입력해주세요.");
      const row: Record<string, string> = {
        external_id: articleId, name: value("name"), property_type: value("property_type"), transaction_type: transaction,
        address: value("address"), area_sqm: value("area_sqm"), source_url: `https://fin.land.naver.com/articles/${articleId}`,
        confirmed_at: confirmed.toISOString(), status: value("status"),
      };
      for (const key of transaction === "purchase" ? ["asking_price"] : transaction === "lease" ? ["deposit"] : ["deposit", "monthly_rent"]) {
        const amount = Number(value(key));
        if (!value(key) || !Number.isSafeInteger(amount) || amount < 0) throw Error("금액은 원 단위 정수로 입력해주세요.");
        row[key] = String(amount);
      }
      const quote = (s: string) => `"${s.replaceAll('"', '""')}"`;
      const csv = Object.keys(row).join(",") + "\n" + Object.values(row).map(quote).join(",");
      lock.current = true; setBusy(true); setMessage("");
      const result = await listingApi.import("네이버페이 부동산 (사용자 확인)", csv, true);
      if (!result.committed) throw Error(result.errors.map(e => e.message).join(" · ") || "저장하지 못했습니다.");
      setMessage(`등록 처리 완료. ${result.warnings.map(w => w.message).join(" · ")} 아래 매물에서 매수 후보로 저장할 수 있습니다. 거래 가능·최근 확인·법정동 연결이 필요하며 전세·월세는 보관만 지원합니다.`);
      onSaved();
      onRegistered?.();
    } catch (error) { setMessage(error instanceof Error ? error.message : "등록에 실패했습니다."); }
    finally { lock.current = false; setBusy(false); }
  };
  const inputClass = "mt-1 block w-full min-w-0 rounded-lg border border-slate-300 p-2.5 outline-none focus:ring-2 focus:ring-primary/30";
  return <><ListingCollector onObserved={onSaved} onManual={url=>{if(busy)return;setSeed({source_url:url,fields:{}});setTransaction("purchase");setMessage("링크를 가져왔습니다. 원문을 직접 확인한 뒤 주소·금액·면적과 거래 상태를 입력해주세요.");}} onApply={item=>{if(busy)return;setSeed(item);setTransaction(item.fields.transaction_type||"purchase");setMessage(item.outcome==="observed"?"추출값을 적용했습니다. 부동산 유형·주소·금액·거래 상태를 확인해주세요.":"링크를 가져왔습니다. 원문을 직접 확인한 뒤 주소·금액·면적과 거래 상태를 입력해주세요.");}} /><section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
    <h2 className="font-bold">관심 매물 링크 등록</h2>
    <p className="text-sm text-slate-600">위에서 불러온 값 또는 직접 확인한 정보를 검토해 저장하세요. 수집 시각은 거래 가능 여부를 보증하지 않습니다. 금액은 원 단위입니다.</p>
    <form onSubmit={submit} key={seed?.observation_id??seed?.source_url??"manual"}>
      <fieldset disabled={busy} className="grid gap-3 text-sm sm:grid-cols-2">
        <label className="sm:col-span-2">네이버 매물 링크<input name="source_url" type="url" defaultValue={seed?.source_url??""} required className={inputClass} placeholder="https://fin.land.naver.com/articles/매물번호" /></label>
        <label>매물 이름<input name="name" defaultValue={seed?.fields.name??initialValues.name??""} required maxLength={150} className={inputClass} /></label>
        <label>부동산 유형<select name="property_type" defaultValue={initialValues.propertyType ?? "apartment"} className={inputClass}>{[["apartment","아파트"],["officetel","오피스텔"],["row_house","연립·다세대"],["detached","단독·다가구"],["non_residential","상업·업무"],["industrial","공장·창고"],["land","토지"]].map(([v,n])=><option value={v} key={v}>{n}</option>)}</select></label>
        <label>확인한 주소<input name="address" defaultValue={seed?.fields.address??initialValues.address??""} required maxLength={500} className={inputClass} placeholder="서울특별시 강남구 역삼동 …" /></label>
        <label>확인한 면적 (㎡)<input name="area_sqm" defaultValue={seed?.fields.area_sqm??""} type="number" min="0.01" step="any" required className={inputClass} /></label>
        <label>거래 유형<select value={transaction} onChange={e=>setTransaction(e.target.value)} className={inputClass}><option value="purchase">매매</option><option value="lease">전세</option><option value="rent">월세</option></select></label>
        {transaction === "purchase" ? <label>확인한 호가 (원)<input name="asking_price" defaultValue={seed?.fields.asking_price??""} type="number" min="1" step="1" required className={inputClass} /></label> : <label>보증금 (원)<input name="deposit" defaultValue={seed?.fields.deposit??""} type="number" min={transaction === "lease" ? 1 : 0} step="1" required className={inputClass} /></label>}
        {transaction === "rent" && <label>월세 (원)<input name="monthly_rent" defaultValue={seed?.fields.monthly_rent??""} type="number" min="1" step="1" required className={inputClass} /></label>}
        <label>원문 확인 일시 (현재 기기 시간대)<input name="confirmed_at" type="datetime-local" required className={inputClass} /></label>
        <label>확인한 거래 상태<select aria-label="확인한 거래 상태" name="status" defaultValue="unknown" className={inputClass}><option value="unknown">미확인</option><option value="active">거래 가능으로 표시됨</option><option value="withdrawn">철회됨</option><option value="completed">거래 완료로 표시됨</option></select></label>
        <button className="rounded bg-primary px-4 py-2 text-white disabled:opacity-40" type="submit">{busy ? "등록 중…" : "관심 매물 등록"}</button>
      </fieldset>
    </form>
    {message && <p role="status" className="text-sm">{message}</p>}
  </section></>;
}
