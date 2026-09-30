"use client";
import { useEffect,useState } from "react";
type Feedback={id:number;feature:string;category:string;message:string;status:string;created:string};
type Metrics={notice:string;steps:Record<string,number>;features:{feature:string;requests:number;failures:number;mean_seconds:number|null;p95_upper_seconds:number|null}[]};
type Backup={status:string;checked_at:number|null;bytes:number|null;notice:string};
const STEP_LABELS:Record<string,string>={case_created:"케이스 생성",conditions_saved:"매수 조건 저장",candidate_added:"후보 등록",comparison_viewed:"후보 비교 조회",candidate_selected:"후보 선택"};
export default function OperationsQualityPanel(){
  const [metrics,setMetrics]=useState<Metrics|null>(null);
  const [backup,setBackup]=useState<Backup|null>(null);
  const [items,setItems]=useState<Feedback[]>([]);
  const [error,setError]=useState("");
  const [refresh,setRefresh]=useState(0);
  const [busy,setBusy]=useState<number|null>(null);
  useEffect(()=>{let cancelled=false;
    async function load(){try{
      const responses=await Promise.all([fetch("/api/operations/metrics",{signal:AbortSignal.timeout(15000)}),fetch("/api/operations/feedback",{signal:AbortSignal.timeout(15000)}),fetch("/api/operations/backup",{signal:AbortSignal.timeout(15000)})]);
      if(responses.some(r=>!r.ok))throw new Error("failed");
      const [m,f,b]=await Promise.all(responses.map(r=>r.json())) as [Metrics,{items:Feedback[]},Backup];
      if(!cancelled){setMetrics(m);setItems(f.items);setBackup(b);setError("");}
    }catch{if(!cancelled)setError("운영 품질 지표를 불러오지 못했습니다.");}}
    void load();const timer=setInterval(()=>void load(),30000);return()=>{cancelled=true;clearInterval(timer);};
  },[refresh]);
  return <><section className="rounded-xl border bg-white p-5"><h2 className="font-bold">정기 DB 백업</h2><p className="mt-2">{({ok:"정상",failed:"실패",stale:"갱신 필요",unknown:"미활성"} as Record<string,string>)[backup?.status??""]??"확인 중"} · {backup?.checked_at?new Date(backup.checked_at*1000).toLocaleString("ko-KR"):"기록 없음"} · {backup?.bytes?`${(backup.bytes/1024/1024).toFixed(1)}MB`:"—"}</p><p className="mt-2 text-xs text-slate-500">{backup?.notice}</p></section><section className="rounded-xl border bg-white p-5"><h2 className="font-bold">최근 7일 사용 단계·실패·처리 시간</h2>
    {error&&<p role="alert" className="text-red-700">{error}</p>}
    <div className="my-3 flex flex-wrap gap-3">{Object.entries(metrics?.steps??{}).map(([key,count])=><p key={key} className="rounded bg-slate-50 p-2">{STEP_LABELS[key]} {count}명</p>)}</div>
    <div className="overflow-x-auto"><table className="w-full text-left text-xs"><thead><tr><th>기능</th><th>실행 수</th><th>실패</th><th>평균</th><th>p95 상한</th></tr></thead><tbody>{metrics?.features.map(row=><tr key={row.feature} className="border-t"><td className="py-2">{row.feature}</td><td>{row.requests}</td><td>{row.failures}</td><td>{row.mean_seconds?.toFixed(2)??"—"}초</td><td>{row.p95_upper_seconds??"—"}초</td></tr>)}</tbody></table></div><p className="mt-2 text-xs text-slate-500">{metrics?.notice}</p>
  </section><section className="rounded-xl border bg-white p-5"><h2 className="font-bold">사용자 문제·개선 의견</h2>
    {items.length===0&&<p className="mt-2 text-sm">접수된 의견이 없습니다.</p>}
    <div className="mt-3 space-y-3">{items.map(item=><article key={item.id} className="rounded border p-3 text-sm"><p>#{item.id} · {item.feature} · {item.category} · {item.created}</p><p className="my-2 whitespace-pre-wrap break-words">{item.message}</p><label>처리 상태<select aria-label={`의견 ${item.id} 처리 상태`} value={item.status} disabled={busy!==null} className="ml-2 rounded border p-2" onChange={async e=>{setBusy(item.id);try{const r=await fetch(`/api/operations/feedback/${item.id}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:e.target.value}),signal:AbortSignal.timeout(15000)});if(!r.ok)throw new Error("failed");setRefresh(v=>v+1);}catch{setError("처리 상태를 저장하지 못했습니다.");}finally{setBusy(null);}}}><option value="open">접수</option><option value="reviewing">검토 중</option><option value="resolved">처리 완료</option></select></label></article>)}</div>
  </section></>;
}
