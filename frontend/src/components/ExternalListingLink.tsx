"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Copy, ExternalLink } from "lucide-react";
import { listingEntryHref, type ListingEntryContext } from "@/lib/listingNavigation";

export default function ExternalListingLink({ query = "", context, showRegistration = true, compact = false }: {
  query?: string; context?: ListingEntryContext; showRegistration?: boolean; compact?: boolean;
}) {
  const searchTerm = context?.address?.trim() || query.trim();
  const [copyResult, setCopyResult] = useState<{ term: string; ok: boolean } | null>(null);
  const copyAddress = async () => {
    try {
      await navigator.clipboard.writeText(searchTerm);
      setCopyResult({ term: searchTerm, ok: true });
    } catch {
      setCopyResult({ term: searchTerm, ok: false });
    }
  };
  const destination = searchTerm
    ? `https://fin.land.naver.com/search?q=${encodeURIComponent(searchTerm)}`
    : "https://fin.land.naver.com/map";
  return <div className={`space-y-2 text-sm ${compact ? "mt-3" : "rounded-xl border border-emerald-100 bg-emerald-50/50 p-4"}`}>
    {searchTerm && <p className="break-words text-xs text-slate-600">검색 주소: <span className="select-text font-medium">{searchTerm}</span></p>}
    <div className="flex flex-wrap gap-2">
      {searchTerm && <button type="button" onClick={copyAddress} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-primary"><Copy size={14} aria-hidden="true" />주소 복사</button>}
      <a href={destination} target="_blank" rel="noopener noreferrer"
        aria-label={`${searchTerm ? `${searchTerm} 네이버 부동산에서 찾기` : "네이버 부동산 지도 열기"} (새 탭)`}
        className="inline-flex items-center gap-2 rounded-lg border border-emerald-200 bg-white px-3 py-2 font-semibold text-primary hover:bg-emerald-50 focus-visible:outline-2 focus-visible:outline-primary">
        {searchTerm ? "네이버 부동산에서 찾기" : "네이버 부동산 지도 열기"}<ExternalLink size={14} aria-hidden="true" /><span className="text-xs font-normal">새 탭</span>
      </a>
      {showRegistration && <Link href={listingEntryHref(context)} className="inline-flex items-center gap-2 rounded-lg bg-primary px-3 py-2 font-semibold text-white hover:bg-primary-strong">
        {context?.name ? "이 단지 매물 등록" : "찾은 매물 등록"}<ArrowRight size={14} aria-hidden="true" />
      </Link>}
    </div>
    {copyResult?.term === searchTerm && <p role="status" className="text-xs text-slate-600">{copyResult.ok ? "주소를 복사했습니다. 네이버 검색창에 붙여넣어 검색하세요." : "주소를 복사하지 못했습니다. 위 검색 주소를 선택해 직접 복사해주세요."}</p>}
    <p className="break-words text-xs leading-5 text-slate-600">{searchTerm ? "검색창이 비어 있으면 주소를 복사해 네이버 검색창에 붙여넣으세요." : "네이버 검색창에 찾는 주소를 입력하세요."}{!compact && " 검색 결과에서 단지·건물을 선택하고 가격·거래 조건을 설정하세요."}{!compact && showRegistration && " 개별 매물을 찾으면 링크를 복사해 이곳에 등록할 수 있습니다."}</p>
  </div>;
}
