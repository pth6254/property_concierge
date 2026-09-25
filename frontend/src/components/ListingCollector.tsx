"use client";

import { useEffect, useRef, useState } from "react";
import { listingApi, ListingRequestError, type ListingObservation } from "@/lib/listings";
import { removeSessionValue, setSessionValue, useSessionValue } from "@/lib/sessionStore";

export const COLLECTION_LABELS: Record<string,string> = {observed:"원문 표시 확인", unavailable:"원문 없음·종료 여부 미확인", blocked:"접근 제한", failed:"조회 실패", parse_error:"정보 식별 실패"};

export default function ListingCollector({ onApply, onObserved, onManual }: { onApply: (item:ListingObservation)=>void; onObserved: ()=>void; onManual: (url:string)=>void }) {
  const pending=useSessionValue("listingCollectionPending");
  const [url,setUrl]=useState(""); const [busy,setBusy]=useState(false); const [message,setMessage]=useState("");
  const [items,setItems]=useState<ListingObservation[]>([]);
  const [retryAt,setRetryAt]=useState<number|null>(null);
  useEffect(()=>{
    if(retryAt===null)return;
    // 대기 종료는 버튼만 다시 켠다. 외부 사이트를 자동 재조회하지 않는다.
    const timer=setTimeout(()=>setRetryAt(null),Math.min(Math.max(0,retryAt-Date.now()),2147483647));
    return()=>clearTimeout(timer);
  },[retryAt]);
  const mounted=useRef(true); const lock=useRef(false); const restored=useRef("");
  const onObservedRef=useRef(onObserved);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{onObservedRef.current=onObserved;},[onObserved]);
  useEffect(()=>{
    if(!pending||restored.current===pending||lock.current)return;
    let saved:{job_id:string;url:string};
    try{saved=JSON.parse(pending);}catch{removeSessionValue("listingCollectionPending");return;}
    restored.current=pending;lock.current=true;
    let cancelled=false;
    const resume=async()=>{
      await Promise.resolve();
      if(cancelled)return;
      setUrl(saved.url);setBusy(true);setMessage("진행 중인 원문 수집을 다시 확인합니다…");
      try{
        const deadline=Date.now()+300000;
        for(;;){
          if(cancelled)return;
          if(Date.now()>deadline)throw Error("작업이 계속 진행 중일 수 있습니다. 새로고침하면 다시 확인합니다.");
          const job=await listingApi.collectionJob(saved.job_id);
          if(job.status==="error"){removeSessionValue("listingCollectionPending");throw Error(job.error||"수집 작업 실패");}
          if(job.status==="done"){removeSessionValue("listingCollectionPending");break;}
          await new Promise(resolve=>setTimeout(resolve,1500));
        }
        const result=await listingApi.observations(saved.url);
        if(!cancelled){setItems(result.items);setMessage(result.items[0]?.message||"수집 기록이 없습니다.");const retry=result.items[0]?.retry_at;if(retry&&retry*1000>Date.now())setRetryAt(retry*1000);onObservedRef.current();}
      }catch(e){if(!cancelled)setMessage(e instanceof Error?e.message:"수집 실패");}
      finally{lock.current=false;if(!cancelled)setBusy(false);}
    };
    void resume();
    return()=>{cancelled=true;lock.current=false;};
  },[pending]);
  const load=async(collect:boolean)=>{
    if(lock.current||(collect&&retryAt!==null))return;lock.current=true;setBusy(true);setMessage(collect?"원문을 조회하고 있습니다…":"이력을 불러오는 중…");setItems([]);
    try{
      if(collect){
        const {job_id}=await listingApi.collect(url);setSessionValue("listingCollectionPending",JSON.stringify({job_id,url}));const deadline=Date.now()+300000;
        for(;;){
          if(!mounted.current)return;
          if(Date.now()>deadline)throw Error("작업이 계속 진행 중일 수 있습니다. 새로고침하면 다시 확인합니다.");
          const job=await listingApi.collectionJob(job_id);
          if(job.status==="error"){removeSessionValue("listingCollectionPending");throw Error(job.error||"수집 작업 실패");}
          if(job.status==="done"){removeSessionValue("listingCollectionPending");break;}
          await new Promise(resolve=>setTimeout(resolve,1500));
        }
      }
      const result=await listingApi.observations(url);
      if(mounted.current){setItems(result.items);setMessage(result.items[0]?.message||"수집 기록이 없습니다.");const retry=result.items[0]?.retry_at;if(retry&&retry*1000>Date.now())setRetryAt(retry*1000);onObserved();}
    }catch(e){if(mounted.current){setMessage(e instanceof Error?e.message:"수집 실패");if(e instanceof ListingRequestError&&e.retryAfterSeconds)setRetryAt(Date.now()+e.retryAfterSeconds*1000);}}
    finally{lock.current=false;if(mounted.current)setBusy(false);}
  };
  return <section className="space-y-3 rounded-xl border border-slate-200 bg-white p-4 sm:p-5">
    <h2 className="font-bold">매물 원문 불러오기 · 시점 이력</h2>
    <p className="text-sm text-slate-600">개별 매물 링크에서 가격·면적·주소를 불러옵니다. 사라진 페이지·접근 실패를 거래 완료로 간주하지 않습니다. 재조회 후에는 내용을 확인해 다시 저장하세요.</p>
    <label className="block text-sm">수집할 매물 링크<input type="url" className="mt-1 w-full rounded border p-2" value={url} disabled={busy} onChange={e=>{setUrl(e.target.value);setItems([]);setMessage("");}} /></label>
    <div className="flex gap-3"><button disabled={busy||!url||retryAt!==null} onClick={()=>load(true)} className="rounded bg-primary px-4 py-2 text-white disabled:opacity-40">{busy?"조회 중…":"원문 수집·재확인"}</button><button disabled={busy||!url} onClick={()=>load(false)} className="underline">수집 이력 조회</button></div>
    {message&&<p role="status" className="text-sm">{message}</p>}
    {retryAt!==null&&<p className="text-sm text-amber-800">{new Date(retryAt).toLocaleString("ko-KR")} 이후 다시 시도할 수 있습니다. 자동으로 재시도하지 않습니다.</p>}
    {retryAt!==null&&items.length===0&&url&&<button disabled={busy} onClick={()=>onManual(url)} className="rounded border px-3 py-2 text-sm">이 링크로 수동 등록</button>}
    {items.slice(0,10).map((item,index)=><article key={item.observation_id} className="space-y-2 border-t pt-3 text-sm">
      <p>{new Date(item.fetched_at*1000).toLocaleString("ko-KR")} · {COLLECTION_LABELS[item.outcome]||item.outcome}</p>
      {item.outcome==="blocked"&&<p>{item.request_sent===false?"대기 시간 중이므로 외부 사이트에 요청하지 않았습니다.":"접근 제한으로 정보를 확인하지 못했습니다. 매물 삭제나 거래 종료를 뜻하지 않습니다."}</p>}
      {index>0&&<p>당시 호가 {item.fields.asking_price?.toLocaleString()??"—"}원 · 보증금 {item.fields.deposit?.toLocaleString()??"—"}원 · 월세 {item.fields.monthly_rent?.toLocaleString()??"—"}원</p>}
      {index===0&&<><p>{item.fields.name} · {item.fields.address} · 전용면적 {item.fields.area_sqm??"미확인"}㎡</p><p>호가 {item.fields.asking_price?.toLocaleString()??"—"}원 · 보증금 {item.fields.deposit?.toLocaleString()??"—"}원 · 월세 {item.fields.monthly_rent?.toLocaleString()??"—"}원</p><p>원문에 표시된 확인일: {item.fields.source_confirmed_date||"미확인"} (수집 시각과 다름)</p>
        {item.outcome==="observed"?<button onClick={()=>onApply(item)} className="rounded border px-3 py-2">추출값을 아래 등록 폼에 적용</button>:<button onClick={()=>onApply({...item,fields:{}})} className="rounded border px-3 py-2">이 링크로 수동 등록</button>}</>}
    </article>)}
  </section>;
}
