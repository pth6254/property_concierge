"use client";

import { useEffect, useRef, useState } from "react";
import { listingApi, type ListingObservation } from "@/lib/listings";

export const COLLECTION_LABELS: Record<string,string> = {observed:"원문 표시 확인", unavailable:"원문 없음·종료 여부 미확인", blocked:"접근 제한", failed:"조회 실패", parse_error:"정보 식별 실패"};

export default function ListingCollector({ onApply, onObserved }: { onApply: (item:ListingObservation)=>void; onObserved: ()=>void }) {
  const [url,setUrl]=useState(""); const [busy,setBusy]=useState(false); const [message,setMessage]=useState("");
  const [items,setItems]=useState<ListingObservation[]>([]);
  const mounted=useRef(true); const lock=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const load=async(collect:boolean)=>{
    if(lock.current)return;lock.current=true;setBusy(true);setMessage(collect?"원문을 조회하고 있습니다…":"이력을 불러오는 중…");setItems([]);
    try{
      if(collect){
        const {job_id}=await listingApi.collect(url);const deadline=Date.now()+120000;
        for(;;){
          if(!mounted.current)return;
          if(Date.now()>deadline)throw Error("조회 대기 시간이 지났습니다. 잠시 후 수집 이력을 확인해주세요.");
          const job=await listingApi.collectionJob(job_id);
          if(job.status==="error")throw Error(job.error||"수집 작업 실패");
          if(job.status==="done")break;
          await new Promise(resolve=>setTimeout(resolve,1500));
        }
      }
      const result=await listingApi.observations(url);
      if(mounted.current){setItems(result.items);setMessage(result.items[0]?.message||"수집 기록이 없습니다.");onObserved();}
    }catch(e){if(mounted.current)setMessage(e instanceof Error?e.message:"수집 실패");}
    finally{lock.current=false;if(mounted.current)setBusy(false);}
  };
  return <section className="space-y-3 rounded-xl border bg-white p-5">
    <h2 className="font-bold">매물 원문 불러오기 · 시점 이력</h2>
    <p className="text-sm text-slate-600">개별 링크를 Playwright로 조회합니다. 사라진 페이지·접근 실패를 거래 완료로 간주하지 않습니다. 재조회 후에는 내용을 확인해 다시 저장하세요.</p>
    <label className="block text-sm">수집할 매물 링크<input type="url" className="mt-1 w-full rounded border p-2" value={url} disabled={busy} onChange={e=>{setUrl(e.target.value);setItems([]);setMessage("");}} /></label>
    <div className="flex gap-3"><button disabled={busy||!url} onClick={()=>load(true)} className="rounded bg-primary px-4 py-2 text-white disabled:opacity-40">{busy?"조회 중…":"원문 수집·재확인"}</button><button disabled={busy||!url} onClick={()=>load(false)} className="underline">수집 이력 조회</button></div>
    {message&&<p role="status" className="text-sm">{message}</p>}
    {items.slice(0,10).map((item,index)=><article key={item.observation_id} className="space-y-2 border-t pt-3 text-sm">
      <p>{new Date(item.fetched_at*1000).toLocaleString("ko-KR")} · {COLLECTION_LABELS[item.outcome]||item.outcome}</p>
      {index>0&&<p>당시 호가 {item.fields.asking_price?.toLocaleString()??"—"}원 · 보증금 {item.fields.deposit?.toLocaleString()??"—"}원 · 월세 {item.fields.monthly_rent?.toLocaleString()??"—"}원</p>}
      {index===0&&<><p>{item.fields.name} · {item.fields.address} · 전용면적 {item.fields.area_sqm??"미확인"}㎡</p><p>호가 {item.fields.asking_price?.toLocaleString()??"—"}원 · 보증금 {item.fields.deposit?.toLocaleString()??"—"}원 · 월세 {item.fields.monthly_rent?.toLocaleString()??"—"}원</p><p>원문에 표시된 확인일: {item.fields.source_confirmed_date||"미확인"} (수집 시각과 다름)</p>
        {item.outcome==="observed"&&<button onClick={()=>onApply(item)} className="rounded border px-3 py-2">추출값을 아래 등록 폼에 적용</button>}</>}
    </article>)}
  </section>;
}
