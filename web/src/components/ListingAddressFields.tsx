"use client";

import { useEffect, useRef, useState } from "react";
import { listingApi, type ListingAddressChoice } from "@/lib/listings";

export default function ListingAddressFields({ initialName = "", initialAddress = "", requireSelection }: {
  initialName?: string; initialAddress?: string; requireSelection: boolean;
}) {
  const [query, setQuery] = useState(initialAddress || initialName);
  const [items, setItems] = useState<ListingAddressChoice[]>([]);
  const [selected, setSelected] = useState<ListingAddressChoice | null>(null);
  const [manual, setManual] = useState(!requireSelection);
  const [name, setName] = useState(initialName);
  const [address, setAddress] = useState(initialAddress);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);

  const search = async () => {
    if (busy) return;
    const id = ++sequence.current;
    if (query.trim().length < 2) { setMessage("주소 또는 단지명을 두 글자 이상 입력해주세요."); return; }
    setBusy(true); setMessage(""); setItems([]);
    try {
      const result = await listingApi.addresses(query.trim());
      if (sequence.current !== id) return;
      setItems(result.items);
      if (!result.items.length) setMessage("상세 주소를 확인하지 못했습니다. 지번·도로명을 구체적으로 입력하거나 직접 입력으로 전환해주세요.");
    } catch (error) {
      if (sequence.current === id) setMessage(error instanceof Error ? error.message : "주소 검색에 실패했습니다.");
    } finally { if (sequence.current === id) setBusy(false); }
  };
  const choose = (item: ListingAddressChoice) => {
    setSelected(item); setManual(false); setAddress(item.jibun_address);
    setName(item.building_name || item.jibun_address.slice(0, 150)); setItems([]); setMessage("");
  };
  const input = "mt-1 block w-full min-w-0 rounded-lg border border-slate-300 p-2.5 outline-none focus:ring-2 focus:ring-primary/30 read-only:bg-slate-50";
  return <div className="space-y-3 rounded-lg border border-slate-200 p-3 sm:col-span-2">
    <div className="flex flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1">주소·단지명 검색<input value={query} maxLength={200} className={input}
        placeholder="도로명주소, 지번주소 또는 아파트 단지명"
        onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); void search(); } }}
        onChange={event => { sequence.current++; setQuery(event.target.value); setItems([]); setSelected(null); setManual(!requireSelection); setBusy(false); setMessage(""); }} /></label>
      <button type="button" disabled={busy} onClick={() => void search()} className="rounded-lg bg-primary px-4 py-2.5 text-white disabled:opacity-40">{busy ? "주소 검색 중…" : "주소 검색"}</button>
    </div>
    {items.length > 0 && <ul aria-label="주소 검색 결과" className="max-h-80 space-y-2 overflow-auto">
      {items.map(item => <li key={item.token}><button type="button" onClick={() => choose(item)} className="w-full rounded-lg border border-slate-200 p-3 text-left hover:border-primary">
        <strong className="block">{item.building_name || "건물명 미확인"}</strong>
        <span className="block text-xs text-slate-600">도로명: {item.road_address || "제공 정보 없음"}</span>
        <span className="block text-xs text-slate-600">지번: {item.jibun_address}</span>
      </button></li>)}
    </ul>}
    {message && <p role="status" className="text-xs text-amber-700">{message}</p>}
    <div className="grid gap-3 sm:grid-cols-2">
      <label>매물 이름<input name="name" value={name} readOnly={!manual} required maxLength={150} className={input} onChange={event => setName(event.target.value)} /></label>
      <label>확인한 주소<input name="address" value={address} readOnly={!manual} required maxLength={500} className={input} onChange={event => setAddress(event.target.value)} /></label>
    </div>
    {selected && <div aria-label="선택한 주소 확인 정보" className="space-y-1 rounded bg-emerald-50 p-3 text-xs">
      <p>도로명: {selected.road_address || "제공 정보 없음"}</p><p>지번: {selected.jibun_address}</p>
      <p>이름 출처: {selected.name_source === "building_register" ? "건축물대장" : selected.name_source === "kakao_address" ? "카카오 주소 검색" : "건물명 미확인"} · 조회일 {new Date(selected.checked_at).toLocaleString("ko-KR")}</p>
      {!selected.building_name && <p>건물명이 확인되지 않아 주소를 등록 이름으로 사용합니다.{selected.name_status === "ambiguous" && " 같은 필지에 서로 다른 이름이 있어 하나로 확정하지 않았습니다."}</p>}
      <p>건물·필지의 주소 확인입니다. 개별 동·호수와 현재 거래 가능 여부는 별도로 확인하세요.</p>
    </div>}
    <input type="hidden" name="address_token" value={selected?.token || ""} />
    <input type="hidden" name="address_mode" value={selected ? "verified" : manual ? "manual" : "unselected"} />
    <button type="button" className="text-xs text-primary underline" onClick={() => { sequence.current++; setBusy(false); setSelected(null); setItems([]); setManual(true); setMessage("직접 입력한 이름·주소는 조회 확인 정보로 표시하지 않습니다."); }}>주소·이름 직접 입력으로 전환</button>
    {!selected && !manual && <p className="text-xs text-slate-500">주소 검색 결과를 선택하면 확인된 이름과 주소가 자동으로 채워집니다.</p>}
  </div>;
}
