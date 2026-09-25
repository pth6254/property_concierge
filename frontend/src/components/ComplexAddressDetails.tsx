import type { ComplexAddress } from "@/lib/types";

export default function ComplexAddressDetails({ item }: { item: ComplexAddress }) {
  const addresses = [["도로명", item.road_address], ["지번", item.jibun_address]];
  return <div className="space-y-1 text-xs text-slate-600">
    {item.address_status === "unavailable" && <p className="text-amber-700">최근 주소 재조회에 실패했습니다. 표시된 이전 주소는 다시 확인해주세요.</p>}
    {addresses.map(([label, address]) => <div key={label} className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <span className="break-words select-text">{label}: {address || "확인되지 않음"}</span>
      {address && <a href={`https://map.naver.com/p/search/${encodeURIComponent(address)}`} target="_blank" rel="noopener noreferrer" aria-label={`${label}주소로 네이버 지도 검색 (새 탭)`} className="font-semibold text-primary underline">네이버 지도 ↗</a>}
    </div>)}
    {item.address_source ? <p className="text-slate-400">주소 출처: {item.address_source}{item.address_checked_at && ` · 조회 ${item.address_checked_at.slice(0, 10)}`}</p> : <p className="text-amber-700">{item.address_status === "ambiguous" ? "동일 이름의 주소가 여러 개여서 단지를 확정하지 못했습니다." : "상세 주소를 확인하지 못했습니다. 동 주소만으로 단지를 확정하지 마세요."}</p>}
    <p className="text-slate-500">지도에서 단지 위치를 확인할 수 있습니다. 현재 매물·호가는 네이버 부동산에서 별도로 확인하세요.</p>
  </div>;
}
