"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import ExternalListingLink from "@/components/ExternalListingLink";
import { COLLECTION_LABELS } from "@/components/ListingCollector";
import ListingLinkForm from "@/components/ListingLinkForm";
import { api } from "@/lib/api";
import { listingApi, type ImportedListing, type ListingImportResult } from "@/lib/listings";
import type { PurchaseCase } from "@/lib/types";

const TYPES = [["apartment","아파트"],["officetel","오피스텔"],["row_house","연립·다세대"],["detached","단독·다가구"],["non_residential","상업·업무"],["industrial","공장·창고"],["land","토지"]];
const STATUS: Record<string,string> = {active:"거래 가능(제공자 표시)",withdrawn:"철회",completed:"거래 완료(제공자 표시)",unknown:"상태 미확인"};
const money = (value: number | null) => value == null ? "—" : `${value.toLocaleString()}원`;

export default function ListingsPage() {
  const [source, setSource] = useState(""); const [csv, setCsv] = useState("");
  const [report, setReport] = useState<ListingImportResult | null>(null);
  const [items, setItems] = useState<ImportedListing[]>([]); const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  const [type, setType] = useState(""); const [transaction, setTransaction] = useState(""); const [budget, setBudget] = useState("");
  const [region, setRegion] = useState(""); const [districts, setDistricts] = useState<{code:string;name:string}[]>([]);
  const [dongs, setDongs] = useState<{code:string;name:string}[]>([]); const [dong, setDong] = useState("");
  const [fresh, setFresh] = useState(false); const [cases, setCases] = useState<PurchaseCase[]>([]); const [caseId, setCaseId] = useState("");
  const [notice, setNotice] = useState(""); const [history, setHistory] = useState<string[]>([]);
  const sequence = useRef(0); const lock = useRef(false);
  const [applied, setApplied] = useState(""); const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let cancelled = false;
    Promise.all([api.marketRegions({level:"sigungu",parent_code:"1100000000"}),api.cases()]).then(([regions, cases])=>{
      if (!cancelled) {setDistricts(regions.items);setCases(cases.items);setCaseId(String(cases.items[0]?.id ?? ""));}
    }).catch(()=>{if(!cancelled)setError("지역·케이스 목록을 불러오지 못했습니다.");});
    return ()=>{cancelled=true;};
  },[]);
  useEffect(()=>{
    if(!region)return;let cancelled=false;
    api.marketRegions({level:"eup_myeon_dong",parent_code:region}).then(r=>{if(!cancelled)setDongs(r.items);}).catch(()=>{if(!cancelled)setError("동 목록을 불러오지 못했습니다.");});
    return ()=>{cancelled=true;};
  },[region]);
  useEffect(()=>{
    const current=++sequence.current;let cancelled=false;
    const params=new URLSearchParams(applied);params.set("page",String(page));
    listingApi.search(params).then(r=>{if(!cancelled&&current===sequence.current){setItems(r.items);setTotal(r.total);}}).catch(e=>{if(!cancelled)setError(e.message);});
    return ()=>{cancelled=true;};
  },[applied,page,refresh]);
  const apply=()=>{
    const p=new URLSearchParams();if(dong||region)p.set("region_code",dong||region);
    if(type)p.set("property_type",type);if(transaction)p.set("transaction_type",transaction);
    if(budget)p.set("budget_max",String(Math.round(Number(budget)*10000)));if(fresh)p.set("fresh_only","true");
    setPage(1);setApplied(p.toString());setRefresh(v=>v+1);setError("");
  };
  const upload=async(commit:boolean)=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError("");setNotice("");
    try{const r=await listingApi.import(source,csv,commit);setReport(r);if(r.committed){setNotice(`신규 ${r.created} · 갱신 ${r.updated} · 동일 ${r.unchanged} · 오래된 자료 제외 ${r.skipped_older}`);setPage(1);setRefresh(v=>v+1);}}
    catch(e){setError(e instanceof Error?e.message:"수입 실패");}finally{lock.current=false;setBusy(false);}
  };
  const save=async(item:ImportedListing)=>{
    if(lock.current)return;lock.current=true;setBusy(true);setError("");
    try{let target=Number(caseId);if(!target){const created=await api.createCase({title:`${item.name} 매수 검토`});target=created.id;setCases(v=>[...v,created]);setCaseId(String(target));}
      await listingApi.saveCandidate(item.id,target);setNotice(`${item.name}을 케이스에 저장했습니다. 케이스에서 AVM·자금 분석을 진행하세요.`);
    }catch(e){setError(e instanceof Error?e.message:"후보 저장 실패");}finally{lock.current=false;setBusy(false);}
  };
  return <div className="mx-auto max-w-6xl space-y-5">
    <h1 className="text-2xl font-bold">매물 보관함</h1>
    <p className="text-sm text-slate-600">본인이 제공받은 매물을 등록·검색합니다. 다른 사용자에게 공개되지 않으며 외부 포털의 실시간 매물 조회가 아닙니다.</p>
    <ExternalListingLink />
    <ListingLinkForm onSaved={()=>{setPage(1);setApplied("");setRefresh(v=>v+1);}} />
    <details className="space-y-3 rounded-xl border bg-white p-5">
      <summary className="cursor-pointer font-bold">여러 매물 등록 (CSV)</summary>
      <p className="text-sm">금액은 <strong>원</strong>, 면적은 ㎡입니다. UTF-8 CSV, 최대 1,000행. <a className="text-primary underline" href="/templates/listings.csv" download>빈 템플릿 다운로드</a></p>
      <label className="block text-sm">출처 이름<input className="ml-2 rounded border p-2" value={source} disabled={busy} onChange={e=>{setSource(e.target.value);setReport(null);}} placeholder="제공 중개업소 또는 직접 등록" /></label>
      <input aria-label="매물 CSV 파일" type="file" accept=".csv,text/csv" disabled={busy} onChange={async e=>{setReport(null);setCsv("");const file=e.target.files?.[0];if(!file)return;if(file.size>1000000){setError("파일은 1MB 이하여야 합니다");return;}try{const text=await file.text();if(text.includes("�"))throw Error("UTF-8 CSV로 저장해주세요");setCsv(text);setError("");}catch(err){setError(err instanceof Error?err.message:"파일 읽기 실패");}}} />
      <p className="text-xs text-slate-500">출처와 원본 매물 ID가 같으면 갱신합니다. 이전 자료에만 있던 매물을 자동 철회하지 않습니다.</p>
      <div className="flex gap-2"><button className="rounded border px-4 py-2 disabled:opacity-40" disabled={busy||!source.trim()||!csv} onClick={()=>upload(false)}>검증·미리보기</button><button className="rounded bg-primary px-4 py-2 text-white disabled:opacity-40" disabled={busy||!report?.valid||report.committed} onClick={()=>upload(true)}>검증된 자료 저장</button></div>
      {report&&<div className="max-h-80 overflow-auto text-sm"><p>총 {report.total}행 · 오류 {report.errors.length}건 · 주의 {report.warnings.length}건{!report.valid&&" — 오류가 있어 저장하지 않습니다"}</p>{[...report.errors,...report.warnings].slice(0,100).map((e,i)=><p key={i}>{e.row}행: {e.message}</p>)}{report.preview.map(r=><p key={r.external_id} className="border-t py-1">{r.external_id} · {r.name} · {r.address} · {r.area_sqm}㎡ · {money(r.asking_price??r.deposit)} · {r.status}</p>)}</div>}
    </details>
    <section className="flex flex-wrap items-end gap-3 rounded-xl border bg-white p-4">
      <label className="text-sm">지역 (서울)<select aria-label="지역 (서울)" className="block rounded border p-2" value={region} onChange={e=>{setRegion(e.target.value);setDong("");setDongs([]);}}><option value="">전체 등록 지역</option>{districts.map(r=><option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
      <label className="text-sm">법정동<select aria-label="법정동" className="block rounded border p-2" disabled={!region} value={dong} onChange={e=>setDong(e.target.value)}><option value="">전체 동</option>{dongs.map(r=><option key={r.code} value={r.code}>{r.name}</option>)}</select></label>
      <label className="text-sm">유형<select className="block rounded border p-2" value={type} onChange={e=>setType(e.target.value)}><option value="">전체 유형</option>{TYPES.map(([v,n])=><option key={v} value={v}>{n}</option>)}</select></label>
      <label className="text-sm">거래<select className="block rounded border p-2" value={transaction} onChange={e=>setTransaction(e.target.value)}><option value="">전체 거래</option><option value="purchase">매매</option><option value="lease">전세</option><option value="rent">월세</option></select></label>
      <label className="text-sm">매매가·보증금 상한 (만원)<input className="block w-40 rounded border p-2" type="number" min="0" value={budget} onChange={e=>setBudget(e.target.value)} /></label>
      <label className="text-sm"><input type="checkbox" checked={fresh} onChange={e=>setFresh(e.target.checked)} /> 최근 7일·거래 가능만</label>
      <button className="rounded bg-primary px-4 py-2 text-white" onClick={apply}>검색</button>
    </section>
    {error&&<p role="alert" className="rounded bg-red-50 p-3 text-red-700">{error}</p>}
    {notice&&<p role="status" className="rounded bg-emerald-50 p-3">{notice} {caseId&&<Link className="text-primary underline" href={`/cases/${caseId}`}>케이스 보기</Link>}</p>}
    <label className="block text-sm">저장할 케이스<select className="ml-2 rounded border p-2" disabled={busy} value={caseId} onChange={e=>setCaseId(e.target.value)}><option value="">새 케이스 생성</option>{cases.map(c=><option key={c.id} value={c.id}>{c.title}</option>)}</select></label>
    <p className="text-sm">총 {total}건 · 확인일이 오래된 매물은 제공자에게 상태를 다시 확인하세요.</p>
    <div className="grid gap-3 md:grid-cols-2">{items.map(item=><article className="space-y-2 rounded-xl border bg-white p-4" key={item.id}>
      <h2 className="font-bold">{item.name}</h2><p className="text-sm">{item.address} · {item.area_sqm}㎡ · {item.floor||"층 미입력"}</p>
      <p>{item.transaction_type==="purchase"?`희망가 ${money(item.asking_price)}`:`보증금 ${money(item.deposit)}${item.monthly_rent?` / 월세 ${money(item.monthly_rent)}`:""}`}</p>
      <p className="text-xs text-slate-600">{STATUS[item.status]} · {item.needs_confirmation?"재확인 필요":"최근 사용자 확인 자료"} · {!item.region_linked&&"법정동 미연결"}</p>
      <p className="text-xs">출처 {item.source_name} / {item.external_id} · 확인 {new Date(item.confirmed_at).toLocaleString("ko-KR")}</p>
      {item.last_collection_at&&<p className="text-xs text-slate-600">최근 수집 시도 {new Date(item.last_collection_at*1000).toLocaleString("ko-KR")} · {COLLECTION_LABELS[item.last_collection_outcome||""]} · 마지막 원문 확인 {item.last_seen_at?new Date(item.last_seen_at*1000).toLocaleString("ko-KR"):"없음"}</p>}
      {item.source_url&&<a href={item.source_url} target="_blank" rel="noopener noreferrer" className="text-xs text-primary underline">원문 확인</a>}
      <div className="flex gap-3"><button disabled={busy||item.needs_confirmation||item.status!=="active"||!item.region_linked||item.transaction_type!=="purchase"} onClick={()=>save(item)} className="rounded border px-3 py-1 text-sm disabled:opacity-40">매수 후보 저장</button><button className="text-sm underline" onClick={async()=>{try{const r=await listingApi.history(item.id);setHistory(r.items.map(h=>`${h.confirmed_at} · ${STATUS[h.status]} · 희망가 ${money(h.asking_price)} · 보증금 ${money(h.deposit)} · 월세 ${money(h.monthly_rent)}`));}catch{setError("이력을 불러오지 못했습니다.");}}}>변경 이력</button></div>
    </article>)}</div>
    {!items.length&&<p className="p-6 text-center text-slate-500">등록된 매물이 없거나 검색 조건에 맞는 자료가 없습니다.</p>}
    <div className="flex gap-3"><button disabled={page===1} onClick={()=>setPage(v=>v-1)}>이전</button><span>{page}페이지</span><button disabled={page*20>=total} onClick={()=>setPage(v=>v+1)}>다음</button></div>
    {!!history.length&&<section className="rounded border bg-white p-4"><h2 className="font-bold">최근 변경 이력 (최대 100건)</h2>{history.map((h,i)=><p key={i} className="text-sm">{h}</p>)}<button className="text-sm underline" onClick={()=>setHistory([])}>닫기</button></section>}
  </div>;
}
