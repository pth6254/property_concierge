"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listingEntryHref } from "@/lib/listingNavigation";
import { listingApi, type ImportedListing } from "@/lib/listings";

function naverArticleUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port ||
        !["land.naver.com", "new.land.naver.com", "fin.land.naver.com", "m.land.naver.com"].includes(url.hostname)) return null;
    const match = /^\/articles\/(\d{1,30})\/?$/.exec(url.pathname);
    const queryIds = url.searchParams.getAll("articleNo");
    const articleId = match?.[1] ?? (queryIds.length === 1 ? queryIds[0] : "");
    return /^\d{1,30}$/.test(articleId) ? `https://fin.land.naver.com/articles/${articleId}` : null;
  } catch {
    return null;
  }
}

export default function VerifiedListingLinks({ regionCode, propertyType, caseId }: {
  regionCode: string; propertyType: string; caseId?: string;
}) {
  const [items, setItems] = useState<ImportedListing[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      region_code: regionCode, transaction_type: "purchase", status: "active",
      fresh_only: "true", page_size: "100",
    });
    if (propertyType !== "all") params.set("property_type", propertyType);
    listingApi.search(params).then((result) => {
      if (!cancelled) setItems(result.items.filter((item) => naverArticleUrl(item.source_url)));
    }).catch(() => { if (!cancelled) setError(true); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [regionCode, propertyType]);

  return <div className="border-b border-slate-100 px-4 py-3 text-xs">
    <strong className="text-slate-700">내가 등록한 이 지역 매물</strong>
    {loading ? <p className="mt-1 text-slate-500">등록 매물을 확인 중입니다.</p>
      : error ? <p className="mt-1 text-slate-500">등록 매물을 불러오지 못했습니다.</p>
      : items.length ? <ul className="mt-2 space-y-1.5">{items.slice(0, 5).map((item) =>
        <li key={item.id}>
          <Link href={listingEntryHref({listingId:String(item.id),caseId})} className="font-semibold text-primary underline">{item.name} · {item.area_sqm}㎡ · 보관함에서 확인</Link>
          <a href={naverArticleUrl(item.source_url) ?? undefined} target="_blank" rel="noopener noreferrer" className="ml-2 text-primary underline">네이버 원문 ↗</a>
          <span className="ml-2 text-slate-500">{new Date(item.confirmed_at).toLocaleDateString("ko-KR")} 확인</span>
        </li>)}</ul>
      : <p className="mt-1 text-slate-500">이 지역에 최근 확인한 네이버 매물이 없습니다. 개별 매물 링크를 등록하면 여기서 원문으로 바로 이동할 수 있습니다.</p>}
  </div>;
}
