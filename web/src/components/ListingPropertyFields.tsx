"use client";

import { useEffect, useRef, useState } from "react";
import ListingAddressFields from "@/components/ListingAddressFields";
import BuildingRegisterDetails from "@/components/BuildingRegisterDetails";
import LandInformationLookup from "@/components/LandInformationDetails";
import { listingApi, type BuildingRegisterResult, type ListingAddressChoice } from "@/lib/listings";

export default function ListingPropertyFields({ initialName = "", initialAddress = "", initialType = "apartment", initialArea, requireSelection }: {
  initialName?: string; initialAddress?: string; initialType?: string; initialArea?: number; requireSelection: boolean;
}) {
  const [address, setAddress] = useState<ListingAddressChoice | null>(null);
  const [propertyType, setPropertyType] = useState(initialType);
  const [dong, setDong] = useState("");
  const [ho, setHo] = useState("");
  const [floor, setFloor] = useState("");
  const [area, setArea] = useState(initialArea === undefined ? "" : String(initialArea));
  const [basis, setBasis] = useState("unknown");
  const [buildingId, setBuildingId] = useState("");
  const [result, setResult] = useState<BuildingRegisterResult | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const sequence = useRef(0);
  useEffect(() => () => { sequence.current++; }, []);
  const invalidate = () => { sequence.current++; setBusy(false); setDirty(true); setMessage(""); };
  const lookup = async (choice: ListingAddressChoice, id = buildingId, buildingDong = dong, unitNumber = ho, type = propertyType) => {
    const requestId = ++sequence.current;
    setBusy(true); setMessage(""); setDirty(true);
    try {
      const value = await listingApi.building({ address_token: choice.token, building_id: id, building_dong: buildingDong, unit_number: unitNumber, property_type: type });
      if (requestId !== sequence.current) return;
      setResult(value); setDirty(false);
    } catch (error) {
      if (requestId === sequence.current) setMessage(error instanceof Error ? error.message : "건축물대장 조회에 실패했습니다. 직접 입력은 계속 사용할 수 있습니다.");
    } finally { if (requestId === sequence.current) setBusy(false); }
  };
  const chooseAddress = (choice: ListingAddressChoice | null) => {
    sequence.current++; setAddress(choice); setResult(null); setBuildingId(""); setDirty(false); setBusy(false); setMessage("");
    if (choice && propertyType !== "land") void lookup(choice, "");
  };
  const input = "mt-1 block w-full min-w-0 rounded-lg border border-slate-300 p-2.5 outline-none focus:ring-2 focus:ring-primary/30";
  const exclusive = result?.unit.status === "found" ? result.unit.exclusive_area_sqm : null;
  const canApply = !dirty && !busy && exclusive != null && exclusive > 0;
  return <div className="min-w-0 space-y-3 sm:col-span-2">
    <ListingAddressFields initialName={initialName} initialAddress={initialAddress} requireSelection={requireSelection} onSelectionChange={chooseAddress} />
    <div className="grid gap-3 sm:grid-cols-2">
      <label>부동산 유형<select aria-label="부동산 유형" name="property_type" value={propertyType} onChange={event => { setPropertyType(event.target.value); invalidate(); }} className={input}>{[["apartment", "아파트"], ["officetel", "오피스텔"], ["row_house", "연립·다세대"], ["detached", "단독·다가구"], ["non_residential", "상업·업무"], ["industrial", "공장·창고"], ["land", "토지"]].map(([value, name]) => <option value={value} key={value}>{name}</option>)}</select></label>
      <label>층 (선택)<input name="floor" maxLength={30} value={floor} onChange={event => setFloor(event.target.value)} className={input} placeholder="예: 10층" /></label>
      <label>건물 동 (선택)<input name="building_dong" maxLength={30} value={dong} onChange={event => { setDong(event.target.value); setBuildingId(""); invalidate(); }} className={input} placeholder="예: 101 또는 A동" /></label>
      <label>호수 (선택)<input name="unit_number" maxLength={30} value={ho} onChange={event => { setHo(event.target.value); invalidate(); }} className={input} placeholder="예: 501 또는 B101호" /></label>
      <p className="text-xs text-slate-500 sm:col-span-2">동·호는 각각 선택 입력입니다. 동이 없는 건물은 호수만 입력하고, 호실이 없는 매물은 둘 다 비워도 등록할 수 있습니다.{propertyType === "detached" && " 다가구의 개별 호 면적은 호(가구)별 면적대장 확인이 필요할 수 있습니다."}{propertyType === "land" && " 토지 면적은 별도 자료로 직접 확인해주세요."}</p>
      <label>면적 기준<select aria-label="면적 기준" name="area_basis" value={basis} onChange={event => setBasis(event.target.value)} className={input}><option value="unknown">확인 필요</option><option value="exclusive">전용면적</option><option value="supply">공급면적</option></select></label>
      <label>확인한 면적 (㎡)<input name="area_sqm" value={area} onChange={event => setArea(event.target.value)} type="number" min="0.01" step="any" required className={input} /></label>
    </div>
    {address && propertyType === "land" && <LandInformationLookup key={address.jibun_address} address={address.jibun_address} />}
    {address && propertyType !== "land" && <div className="space-y-3">
      {result && result.buildings.length > 1 && <label className="block text-sm">조회할 건물 선택<select aria-label="조회할 건물 선택" value={buildingId || result.selected_building?.id || ""} className={input} onChange={event => {
        const selected = result.buildings.find(building => building.id === event.target.value);
        setBuildingId(event.target.value); setDong(selected?.dong_name || "");
        void lookup(address, event.target.value, selected?.dong_name || "");
      }}><option value="">건물을 선택해주세요</option>{result.buildings.map(building => <option key={building.id} value={building.id}>{building.building_name || "건물명 미제공"} {building.dong_name || "동명칭 없음"}{building.auxiliary ? " · 부속건축물" : ""} · {building.fields.use || "용도 미제공"}</option>)}</select></label>}
      <button type="button" disabled={busy} className="rounded-lg border border-primary px-3 py-2 text-sm text-primary disabled:opacity-40" onClick={() => void lookup(address)}>{busy ? "건축물대장 조회 중…" : "건물·호실 정보 조회"}</button>
      {busy && <p role="status" className="text-xs text-slate-500">공식 건물 정보를 조회하고 있습니다. 등록 항목은 계속 직접 입력할 수 있습니다.</p>}
      {result && <BuildingRegisterDetails evidence={result} stale={dirty} />}
      {canApply && <div className="space-y-2 rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-sm">
        <p>조회한 전유면적: {exclusive} ㎡{area && Number(area) !== exclusive ? ` · 현재 입력 면적 ${area} ㎡와 다릅니다.` : ""}</p>
        <button type="button" className="rounded bg-primary px-3 py-2 text-white" onClick={() => {
          setArea(String(exclusive)); setBasis("exclusive");
          if (result?.unit.floor) setFloor(result.unit.floor);
          setMessage("조회한 전유면적과 제공된 층을 적용했습니다. 다른 등록 조건과 현재 매물의 동·호를 확인해주세요.");
        }}>조회 정보 적용</button>
      </div>}
      <input type="hidden" name="building_token" value={!dirty && !busy ? result?.building_token || "" : ""} />
    </div>}
    {message && <p role="status" className="text-sm text-amber-700">{message}</p>}
  </div>;
}
