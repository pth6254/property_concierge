import type { BuildingRegisterEvidence, RegisterFields } from "@/lib/listings";

const fields: [string, string, string?][] = [
  ["use", "주용도"], ["other_use", "기타용도"], ["structure", "구조"], ["roof", "지붕"],
  ["approval_date", "사용승인일"], ["above_ground_floors", "지상층수", "층"], ["underground_floors", "지하층수", "층"],
  ["households", "세대수", "세대"], ["families", "가구수", "가구"], ["unit_count", "호수", "호"],
  ["land_area_sqm", "대지면적", "㎡"], ["building_area_sqm", "건축면적", "㎡"], ["total_area_sqm", "연면적", "㎡"],
  ["far_area_sqm", "용적률 산정 연면적", "㎡"], ["building_coverage_pct", "건폐율", "%"], ["floor_area_ratio_pct", "용적률", "%"],
  ["height_m", "건물 높이", "m"], ["total_parking", "총 주차대수", "대"],
  ["indoor_self_parking", "옥내 자주식 주차", "대"], ["outdoor_self_parking", "옥외 자주식 주차", "대"],
  ["indoor_mechanical_parking", "옥내 기계식 주차", "대"], ["outdoor_mechanical_parking", "옥외 기계식 주차", "대"],
  ["passenger_elevators", "승용 승강기", "대"], ["emergency_elevators", "비상용 승강기", "대"],
  ["main_buildings", "주건축물", "동"], ["auxiliary_buildings", "부속건축물", "동"], ["auxiliary_area_sqm", "부속건축물 면적", "㎡"],
  ["permit_date", "건축허가일"], ["construction_date", "착공일"], ["record_created_date", "자료 생성일"],
  ["earthquake_design", "내진설계 적용"], ["earthquake_capacity", "내진능력"],
  ["energy_grade", "에너지효율등급"], ["energy_saving_pct", "에너지절감률", "%"], ["epi_score", "EPI 점수"],
  ["green_grade", "친환경 인증등급"], ["green_score", "친환경 인증점수"],
  ["intelligent_grade", "지능형 건축물 등급"], ["intelligent_score", "지능형 건축물 인증점수"],
];
function display(value: string | number | null | undefined, unit = "") {
  if (value == null || value === "") return "미제공";
  return (typeof value === "number" ? value.toLocaleString("ko-KR", { maximumFractionDigits: 6 }) : value) + (unit ? ` ${unit}` : "");
}
function FieldList({ values }: { values: RegisterFields }) {
  const available = fields.filter(([key]) => values[key] != null && values[key] !== "");
  if (!available.length) return <p className="text-xs text-slate-500">상세 항목이 제공되지 않았습니다.</p>;
  return <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">{available.map(([key, label, unit]) => <div key={key} className="flex min-w-0 justify-between gap-3">
    <dt className="text-slate-500">{label}</dt><dd className="break-words text-right">{display(values[key], unit)}</dd>
  </div>)}</dl>;
}
export default function BuildingRegisterDetails({ evidence, stale = false }: { evidence: BuildingRegisterEvidence; stale?: boolean }) {
  const building = evidence.selected_building;
  const unit = evidence.unit;
  const checked = evidence.record_checked_at?.getBrTitleInfo || evidence.checked_at;
  return <div aria-label="건축물대장 조회 정보" className="min-w-0 space-y-3 rounded-lg border border-slate-200 bg-slate-50 p-3">
    <div><p className="font-semibold">건축물대장 기준 정보</p><p className="text-xs text-slate-500">공식 공개자료 · 조회 시각 {new Date(checked).toLocaleString("ko-KR")}</p></div>
    {stale && <p role="status" className="text-sm text-amber-700">입력 조건이 바뀌었습니다. 아래는 이전 조회값이며 적용하려면 다시 조회해주세요.</p>}
    {evidence.status === "unavailable" && <p className="text-sm text-amber-700">공식 자료를 조회하지 못했습니다. 직접 입력은 계속 사용할 수 있습니다.</p>}
    {evidence.status === "not_found" && <p className="text-sm">해당 필지의 건축물대장 기록을 찾지 못했습니다.</p>}
    {building && <div className="space-y-2"><p className="text-sm font-medium">선택한 건물: {building.building_name || "건물명 미제공"} {building.dong_name}{building.auxiliary && " · 부속건축물"}</p>
      <dl className="grid grid-cols-2 gap-2 text-sm">{["use", "structure", "approval_date", "above_ground_floors"].map(key => {
        const descriptor = fields.find(row => row[0] === key);
        return <div key={key}><dt className="text-xs text-slate-500">{descriptor?.[1]}</dt><dd>{display(building.fields[key], descriptor?.[2])}</dd></div>;
      })}</dl>
      <details><summary className="cursor-pointer text-sm text-primary">건물 면적·주차·승강기·인증 상세</summary><div className="mt-3"><FieldList values={building.fields} /></div></details>
    </div>}
    {!building && evidence.status !== "unavailable" && evidence.status !== "not_found" && <p className="text-sm text-amber-700">여러 건물이 있거나 동을 특정하지 못했습니다. 건물을 선택하면 상세 정보를 확인할 수 있습니다.</p>}
    {evidence.complex && <details><summary className="cursor-pointer text-sm text-primary">단지·대지 전체 정보</summary><div className="mt-3"><FieldList values={evidence.complex.fields} /></div></details>}
    {unit.status !== "not_requested" && <div aria-label="호실 조회 결과" className="space-y-1 rounded border border-slate-200 bg-white p-3 text-sm">
      <p className="font-medium">호실 정보 {unit.dong_name} {unit.unit_name}</p>
      {unit.register_id && <><p>전유면적: {display(unit.exclusive_area_sqm, "㎡")}</p><p>층: {unit.floor || "미제공·복수층"} · 용도: {unit.use || "미제공"}</p></>}
      <p className="text-xs text-slate-600">{unit.message}</p>
      {unit.checked_at && <p className="text-xs text-slate-500">호실 자료 조회 시각 {new Date(unit.checked_at).toLocaleString("ko-KR")}</p>}
      {(unit.common_areas?.length ?? 0) > 0 && <details><summary className="cursor-pointer text-xs text-primary">공용면적 기록 확인</summary><ul className="mt-2 space-y-1 text-xs">{unit.common_areas?.map((area, index) => <li key={index}>{area.floor || "층 미제공"} · {area.use || "용도 미제공"} · {display(area.area_sqm, "㎡")}</li>)}</ul><p className="mt-2 text-xs text-slate-500">공용면적 전체를 더한 값이 광고의 공급면적과 같다고 판단하지 않습니다.</p></details>}
      {evidence.area_matches_input !== undefined && <p className="text-xs text-slate-500">{evidence.area_matches_input ? "등록한 전용면적이 조회한 전유면적과 일치합니다." : "등록 면적은 조회한 전유면적과 다르거나 면적 기준 확인이 필요합니다."}</p>}
    </div>}
    {evidence.floors.length > 0 && <details><summary className="cursor-pointer text-sm text-primary">선택한 건물의 층별 용도·면적</summary><ul className="mt-2 space-y-1 text-xs">{evidence.floors.map((floor, index) => <li key={index}>{floor.floor} · {floor.use || floor.other_use || "용도 미제공"} · {floor.structure || "구조 미제공"} · {display(floor.area_sqm, "㎡")}</li>)}</ul><p className="mt-2 text-xs text-slate-500">층 면적은 개별 호의 전용면적과 구분합니다.</p></details>}
    {evidence.zones.length > 0 && <p className="text-xs">대장 기재 지역·지구·구역: {evidence.zones.map(zone => zone.name || zone.other).filter(Boolean).join(" · ")}</p>}
    {evidence.sanitation.length > 0 && <details><summary className="cursor-pointer text-xs text-primary">오수정화시설</summary><ul className="mt-2 space-y-1 text-xs">{evidence.sanitation.map((item, index) => <li key={index}>{item.type || "형식 미제공"} · {display(item.capacity_people, "인용")} · {display(item.capacity_m3, "㎥")}</li>)}</ul></details>}
    <ul className="space-y-1 text-xs text-slate-500">{evidence.notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
  </div>;
}
