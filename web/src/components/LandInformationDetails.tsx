"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { LandInformation } from "@/lib/valuation";

const STATUS: Record<string, string> = { found: "조회됨", partial: "일부 확인", unavailable: "조회 미완료",
  not_found: "자료 없음", not_configured: "API 설정 필요", key_expired: "API 키 만료",
  incomplete: "일부 응답 누락", ambiguous: "중복 자료 확인 필요", parcel_mismatch: "필지 불일치",
  no_dated_record: "기준일에 맞는 자료 없음", invalid_response: "응답 확인 필요", provider_error: "공급기관 조회 오류", request_error: "연결 실패" };
const show = (value: string | number | null, unit = "") => value == null ? "미확인" : typeof value === "number" ? `${value.toLocaleString("ko-KR")}${unit}` : value;

export function LandInformationDetails({ value }: { value: LandInformation }) {
  const f = value.fields;
  const rows: [string, string][] = [["필지고유번호", value.pnu], ["지번", value.address], ["도로명", value.road_address || "제공 정보 없음"],
    ["토지대장 면적", show(f.land_area_sqm, "㎡")], ["지목", show(f.land_category)],
    ["이용상황", show(f.actual_use)], ["지형고저", show(f.terrain_height)], ["형상", show(f.terrain_shape)],
    ["도로접면", show(f.road_frontage)], ["용도지역", [f.zone_primary, f.zone_secondary].filter(Boolean).join(" · ") || "미확인"],
    ["특성 기준연도", value.characteristics_year || "미확인"],
    ["개별공시지가", show(f.official_price_won_per_sqm, "원/㎡")], ["공시지가 기준연도", value.official_price_year || "미확인"],
    ["공시 참고 총액", show(value.official_reference_total_won, "원")],
    ["공시 총액 계산 면적", show(value.official_reference_area_sqm, "㎡")]];
  return <section aria-label="토지 공개정보" className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm">
    <h3 className="font-semibold">필지 공개정보 · {STATUS[value.status] || "확인 필요"}</h3>
    <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-2 break-words">{rows.map(([label, content]) => <div key={label} className="contents"><dt className="text-slate-500">{label}</dt><dd>{content}</dd></div>)}</dl>
    <p className="text-xs text-slate-600">공시 참고 총액은 같은 기준연도의 토지특성 면적 × 개별공시지가입니다. 현재 토지대장 면적과 다를 수 있습니다.</p>
    <h4 className="font-medium">토지이용계획</h4>
    {value.land_use.length ? <ul className="space-y-1">{value.land_use.map((item, index) => <li key={index}>{item.name || "명칭 미확인"} · {item.conflict || "저촉 여부 미확인"}</li>)}</ul> : <p>이용계획 미확인 — 제한이 없다는 뜻은 아닙니다.</p>}
    <details><summary className="cursor-pointer text-primary">출처와 자료 시점</summary><ul className="mt-2 space-y-2">{value.sources.map(source => <li key={source.id}>
      <a href={source.url} target="_blank" rel="noreferrer" className="underline">{source.title}</a> · {STATUS[source.status] || "확인 필요"}
      <span className="block text-xs">기준연도 {source.reference_year || "제공 안 됨"} · 자료 갱신 {source.record_updated_at || "제공 안 됨"} · 조회 {new Date(source.checked_at).toLocaleString("ko-KR")}</span>
    </li>)}</ul></details>
    {value.limitations.map(text => <p key={text} className="text-xs text-amber-800">{text}</p>)}
  </section>;
}

export default function LandInformationLookup({ address, asOfDate = "" }: { address: string; asOfDate?: string }) {
  const [value, setValue] = useState<LandInformation | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void api.landInformation(address, asOfDate, controller.signal).then(result => {
      if (!controller.signal.aborted) { setValue(result); setError(""); }
    }).catch(() => { if (!controller.signal.aborted) setError("필지 조회를 완료하지 못했습니다. 정확한 지번 주소를 선택하고 다시 시도해주세요."); });
    return () => controller.abort();
  }, [address, asOfDate, retry]);
  return <div className="my-4">{value ? <LandInformationDetails value={value} /> : <p role="status" className="text-sm text-slate-600">{error || "필지 공개정보를 자동 조회하고 있습니다…"}</p>}
    {(error || (value && value.status !== "found")) && <button type="button" className="mt-2 text-sm text-primary underline" onClick={() => { setValue(null); setError(""); setRetry(value => value + 1); }}>토지 정보 다시 조회</button>}
  </div>;
}
