"use client";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { setSessionValue, useSessionValue } from "@/lib/sessionStore";
import type { ComplexAddress } from "@/lib/types";

type Health = {status:string; checks:Record<string,string>; queue:{waiting:number|null;in_progress:number|null;oldest_wait_seconds:number|null}; alerts:{id:string;status:string;at:string;checks:Record<string,string>}[]};
type Catalog = {total:number;page:number;items:{id:number;name:string;dong:string;aliases:string[];status:string;address:ComplexAddress;checked_at:number}[]};
type Ingestion = {region:string;counts:Record<string,number>;items:{endpoint:string;category:string;month:string;status:string;count:number;fetched_at:number|null}[]};
type Quality = {counts:Record<string,number>;notice:string};
type Job = {status:string;error?:string;step?:string};
const labels:Record<string,string> = {ok:"정상",down:"연결 끊김",unknown:"미확인",delayed:"지연",ready:"정상",degraded:"점검 필요",database:"DB",redis:"Redis",worker:"작업 실행기",queue:"작업 큐",completed:"수집 완료",missing:"누락",failed:"실패",stale:"갱신 필요",running:"실행 중",interrupted:"중단 의심",matched:"주소 일치",unresolved:"미확인",ambiguous:"여러 주소",unavailable:"조회 실패"};
async function request<T>(path:string, body?:object):Promise<T> {
  const response=await fetch(`/api/operations/${path}`,{method:body?"POST":"GET",headers:{"Content-Type":"application/json"},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(15000)});
  if(!response.ok){const value=await response.json().catch(()=>null);throw new Error(value?.detail || `요청 실패 (${response.status})`);}
  return response.json();
}
const date=(value:number|null)=>value?new Date(value*1000).toLocaleString("ko-KR"):"기록 없음";
const button="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:opacity-40";

export default function OperationsPage(){
  const {user,loading}=useAuth();
  const [health,setHealth]=useState<Health|null>(null);
  const [catalog,setCatalog]=useState<Catalog|null>(null);
  const [ingestion,setIngestion]=useState<Ingestion|null>(null);
  const [quality,setQuality]=useState<Quality|null>(null);
  const [lawd,setLawd]=useState("11350");
  const [scope,setScope]=useState("11350");
  const [page,setPage]=useState(1);
  const [refresh,setRefresh]=useState(0);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [dataLoading,setDataLoading]=useState(true);
  const jobId=useSessionValue("operationsJobId");
  const [job,setJob]=useState<Job|null>(null);
  useEffect(()=>{
    if(!user?.is_operator)return;
    let cancelled=false;
    async function load(){try{const value=await request<Health>("status");if(!cancelled)setHealth(value);}catch(e){if(!cancelled)setError(e instanceof Error?e.message:"상태 조회 실패");}}
    void load();const timer=setInterval(()=>void load(),15000);
    return()=>{cancelled=true;clearInterval(timer);};
  },[user?.is_operator]);
  useEffect(()=>{
    if(!user?.is_operator)return;
    let cancelled=false;
    async function load(){try{
      const [c,i,q]=await Promise.all([request<Catalog>(`complexes?lawd_code=${scope}&page=${page}`),request<Ingestion>(`ingestion?lawd_code=${scope}`),request<Quality>("listing-quality")]);
      if(!cancelled){setCatalog(c);setIngestion(i);setQuality(q);setError("");}
    }catch(e){if(!cancelled)setError(e instanceof Error?e.message:"현황 조회 실패");}finally{if(!cancelled)setDataLoading(false);}}
    void load();return()=>{cancelled=true;};
  },[scope,page,refresh,user?.is_operator]);
  useEffect(()=>{
    if(!jobId || !user?.is_operator)return;
    let cancelled=false;const started=Date.now();let timer:ReturnType<typeof setTimeout>;
    async function poll(){try{const value=await request<Job>(`jobs/${jobId}`);if(cancelled)return;setJob(value);
      if(["done","error"].includes(value.status)){setRefresh(v=>v+1);return;}
      if(Date.now()-started>180000){setError("작업이 계속 진행 중입니다. 새로고침하면 상태 조회를 재개합니다.");return;}
      timer=setTimeout(()=>void poll(),2000);
    }catch(e){if(!cancelled)setError(e instanceof Error?e.message:"작업 조회 실패");}}
    void poll();return()=>{cancelled=true;clearTimeout(timer);};
  },[jobId,user?.is_operator]);
  async function enqueue(path:string,body:object){setBusy(true);setError("");try{const value=await request<{job_id:string}>(path,body);setJob({status:"queued"});setSessionValue("operationsJobId",value.job_id);}catch(e){setError(e instanceof Error?e.message:"요청 실패");}finally{setBusy(false);}}
  if(loading)return <p>권한 확인 중…</p>;
  if(!user?.is_operator)return <div className="p-8"><h1 className="text-xl font-bold">운영 관리</h1><p>운영자 권한이 필요한 화면입니다.</p></div>;
  return <div className="mx-auto max-w-6xl space-y-6">
    <h1 className="text-2xl font-bold">운영 관리</h1>
    <p className="text-sm text-slate-600">상태는 15초마다 확인합니다. 재처리는 선택한 항목만 실행하며 외부 API 사용량이 발생할 수 있습니다.</p>
    {error&&<p role="alert" className="rounded bg-red-50 p-3 text-red-700">{error}</p>}
    <section className="rounded-xl border bg-white p-5"><h2 className="font-bold">서비스 준비 상태 · {labels[health?.status||""]||"확인 중"}</h2>
      <div className="my-3 flex flex-wrap gap-3">{Object.entries(health?.checks||{}).map(([key,value])=><span key={key} className={`rounded px-3 py-2 ${value==="ok"?"bg-emerald-50":"bg-amber-50"}`}>{labels[key]}: {labels[value]||value}</span>)}</div>
      <p>대기 {health?.queue.waiting??"—"}건 · 처리 중 {health?.queue.in_progress??"—"}건 · 가장 오래 기다린 작업 {health?.queue.oldest_wait_seconds??"—"}초</p>
      <details className="mt-3"><summary>장애·복구 알림 기록</summary><ul className="mt-2 space-y-2">{health?.alerts.map(a=><li key={a.id}>{date(Number(a.at))} · {labels[a.status]} · {Object.entries(a.checks).map(([k,v])=>`${labels[k]} ${labels[v]||v}`).join(" / ")}</li>)}</ul></details>
    </section>
    <form onSubmit={e=>{e.preventDefault();if(!/^\d{5}$/.test(lawd)){setError("시군구코드 5자리를 입력하세요.");return;}setDataLoading(true);setCatalog(null);setIngestion(null);setScope(lawd);setPage(1);setRefresh(v=>v+1);}} className="flex flex-wrap items-end gap-3">
      <label className="text-sm">시군구코드 (노원 11350 / 서초 11650)<input value={lawd} onChange={e=>setLawd(e.target.value)} pattern="[0-9]{5}" className="mt-1 block rounded border p-2"/></label><button className={button}>지역 현황 조회</button>
    </form>
    {dataLoading&&<p role="status">데이터 현황 조회 중…</p>}
    {jobId&&<p role="status" className="rounded bg-slate-100 p-3">최근 요청: {job?.status||"조회 중"} {job?.step} {job?.error}</p>}
    <section className="rounded-xl border bg-white p-5"><h2 className="font-bold">단지 기준정보 · {catalog?.total??0}개</h2><div className="mt-3 space-y-3">{catalog?.items.map(c=><article key={c.id} className="rounded border p-3 text-sm">
      <p className="font-bold">#{c.id} {c.name} · {c.dong} · {labels[c.status]||c.status}</p><p>도로명: {c.address.road_address||"미확인"}</p><p>지번: {c.address.jibun_address||"미확인"}</p><p>별칭: {c.aliases.join(", ")}</p><p>출처: {c.address.address_source||"미확인"} · 마지막 시도 {date(c.checked_at)}</p>
      <button className={`${button} mt-2`} disabled={busy} onClick={()=>void enqueue(`complexes/${c.id}/refresh`,{})}>주소 재확인</button>
    </article>)}</div>{catalog?.total===0&&<p className="mt-2 text-sm">이 지역에서 새로 단지 추천을 실행하면 기준정보가 생성됩니다.</p>}
    <div className="mt-3 flex gap-2"><button className={button} disabled={page<=1} onClick={()=>setPage(p=>p-1)}>이전</button><span>{page}페이지</span><button className={button} disabled={page*30>=(catalog?.total||0)} onClick={()=>setPage(p=>p+1)}>다음</button></div></section>
    <section className="rounded-xl border bg-white p-5"><h2 className="font-bold">실거래 갱신 · {ingestion?.region} · 최근 12개월</h2><p className="my-2 text-sm">{Object.entries(ingestion?.counts||{}).map(([s,n])=>`${labels[s]||s} ${n}`).join(" · ")}</p>
      <div className="max-h-96 overflow-auto"><table className="w-full min-w-[660px] text-left text-sm"><thead><tr><th>원천 / 유형</th><th>거래월</th><th>상태</th><th>건수</th><th>마지막 수집</th><th>작업</th></tr></thead><tbody>{ingestion?.items.map(i=><tr key={`${i.endpoint}:${i.month}`} className="border-t"><td className="py-2">{i.endpoint}<br/>{i.category}</td><td>{i.month}</td><td>{labels[i.status]||i.status}</td><td>{i.count}</td><td>{date(i.fetched_at)}</td><td>{["failed","missing","stale","interrupted"].includes(i.status)&&<button disabled={busy} className={button} onClick={()=>void enqueue("ingestion/retry",{lawd_code:scope,endpoint:i.endpoint,month:i.month})}>이 월 재수집</button>}</td></tr>)}</tbody></table></div>
    </section>
    <section className="rounded-xl border bg-white p-5"><h2 className="font-bold">매물 원문 수집 상태</h2><p className="my-2">{Object.entries(quality?.counts||{}).map(([key,n])=>`${key}: ${n}건`).join(" · ")||"수집 기록 없음"}</p><p className="text-sm text-slate-600">{quality?.notice}</p></section>
  </div>;
}
