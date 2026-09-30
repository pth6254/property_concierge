"use client";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function ServiceFeedbackForm() {
  const {user}=useAuth();
  const pathname=usePathname();
  const [category,setCategory]=useState("error");
  const [message,setMessage]=useState("");
  const [result,setResult]=useState("");
  const [busy,setBusy]=useState(false);
  const page=pathname.split("/")[1];
  const feature=["explore","recommendation","cases","appraisal","simulation","rights","chat","listings"].includes(page)?page:"other";
  if(!user)return null;
  return <details className="mt-8 max-w-2xl rounded-xl border border-slate-200 bg-white p-4 text-sm">
    <summary className="cursor-pointer font-semibold">사용 중 문제·개선 의견 보내기</summary>
    <form className="mt-3 space-y-3" onSubmit={async e=>{
      e.preventDefault();if(busy)return;setBusy(true);setResult("");
      try{
        const response=await fetch("/api/feedback",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({feature,category,message}),signal:AbortSignal.timeout(15000)});
        if(!response.ok)throw new Error("failed");
        setMessage("");setResult("의견을 접수했습니다. 운영자가 확인합니다.");
      }catch{setResult("의견을 보내지 못했습니다. 잠시 후 다시 시도해주세요.");}finally{setBusy(false);}
    }}>
      <label className="block">의견 종류<select aria-label="의견 종류" value={category} onChange={e=>setCategory(e.target.value)} className="ml-2 rounded border p-2"><option value="error">오류 발생</option><option value="confusing">사용 방법이 어려움</option><option value="incorrect">결과 확인 필요</option><option value="suggestion">개선 제안</option></select></label>
      <label className="block">문제 상황<textarea aria-label="문제 상황" minLength={3} maxLength={2000} required value={message} onChange={e=>setMessage(e.target.value)} className="mt-1 block w-full rounded border p-2" placeholder="어떤 작업에서 막혔는지 알려주세요. 주소·연락처·금융 정보는 입력하지 마세요." /></label>
      <button disabled={busy} className="rounded bg-primary px-3 py-2 text-white disabled:opacity-40">{busy?"보내는 중…":"의견 보내기"}</button>
      {result&&<p role="status">{result}</p>}
    </form>
  </details>;
}
