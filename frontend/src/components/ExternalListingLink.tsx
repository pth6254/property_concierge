"use client";

import { useState } from "react";
import Link from "next/link";

export default function ExternalListingLink({ query = "" }: { query?: string }) {
  const [message, setMessage] = useState("");
  return <div className="my-3 space-y-2 text-sm">
    <a href="https://land.naver.com/" target="_blank" rel="noopener noreferrer" className="font-semibold text-primary underline">네이버페이 부동산에서 매물 보기 ↗</a>
    {query && <div><span>검색할 지역·단지: {query} </span><button type="button" className="underline" onClick={async () => {
      try { await navigator.clipboard.writeText(query); setMessage("검색어를 복사했습니다."); }
      catch { setMessage("복사하지 못했습니다. 위 검색어를 직접 입력해주세요."); }
    }}>검색어 복사</button></div>}
    <p className="text-xs text-slate-500">외부 페이지에서 검색어와 가격·거래 조건을 입력하세요. 검색 조건은 자동 적용되지 않습니다.</p>
    <Link href="/listings" className="text-primary underline">확인한 매물 링크 등록하기</Link>
    {message && <p role="status">{message}</p>}
  </div>;
}
