import type { ValuationAssessment } from "@/lib/valuation";

const kinds = { market_reference: "시장가격 참고", conditional_scenario: "조건부 시나리오", public_reference: "공개자료 참고", partial_reference: "구성 부분 참고", withheld: "추정 보류", unsupported: "지원 범위 밖" };
const scopes: Record<string, string> = { single_unit: "개별 호실", whole_building: "건물 전체", land_and_building: "토지와 건물", single_parcel: "단일 필지", unknown: "미확인" };
const areas: Record<string, string> = { exclusive: "전용면적", supply: "공급면적", gross: "연면적", land: "토지면적", unknown: "면적 기준 미확인" };
const methods: Record<string, string> = { sales_comparison: "실거래 비교", income_scenario: "임대료 수익 시나리오", land_public_data: "토지 공개정보", catboost: "CatBoost 가격 모델" };
const sources: Record<string, string> = { user_input: "사용자 입력", official_data: "공식자료", analysis: "분석 결과", policy: "서비스 기준" };

function JeonseRatio({ value }: { value: NonNullable<ValuationAssessment["jeonse_context"]> }) {
  const pct = value.ratio_pct;
  return <details open className="rounded bg-white p-3 ring-1 ring-slate-200">
    <summary className="cursor-pointer font-semibold">전세가율 참고 · {value.complex_name}{pct != null ? ` ${pct}%` : ""}</summary>
    <p className="mt-1 text-xs text-slate-600">최근 {value.window_months}개월 동일 단지 전용면적 ±{value.area_tolerance_pct}%의 전세 {value.lease_count}건(갱신 계약 {value.renewal_count}건 포함)과 매매 {value.sale_count}건의 ㎡당 중앙값을 비교했습니다. 시점이 다른 신고를 섞었고 가격 추정에는 사용하지 않습니다.</p>
    {pct != null && <p className="mt-2">전세 ㎡당 {manwon(value.lease_per_sqm_median_won ?? 0)} ÷ 매매 ㎡당 {manwon(value.sale_per_sqm_median_won ?? 0)}</p>}
    {!value.sufficient && <p className="mt-2 rounded bg-amber-50 p-2 text-amber-900">전세 또는 매매 신고가 각 3건 미만이라 참고 수준이 낮습니다. 위험 여부를 판단하지 마세요.</p>}
    {value.missing_months > 0 && <p className="mt-1 text-xs text-amber-800">전월세 조회를 마치지 못한 달이 {value.missing_months}개월 있습니다.</p>}
    <ul className="mt-2 space-y-1">{value.leases.map(l => <li key={`${l.deal_date}-${l.area_sqm}-${l.deposit_won}`}>{l.deal_date} · {l.area_sqm}㎡ · 보증금 {won(l.deposit_won)}{l.renewal ? " · 갱신" : ""}</li>)}</ul>
  </details>;
}

const won = (n: number) => `${(n / 100_000_000).toFixed(2)}억`;
const manwon = (n: number) => `${Math.round(n / 10_000).toLocaleString()}만원`;

function ReferenceTrades({ value }: { value: NonNullable<ValuationAssessment["reference_context"]> }) {
  return <details open className="rounded bg-white p-3 ring-1 ring-slate-200">
    <summary className="cursor-pointer font-semibold">직접 확인용 {value.complex_name} 최근 {value.window_months}개월 거래 {value.trade_count}건</summary>
    <p className="mt-1 text-xs text-slate-600">전용면적 ±{value.area_tolerance_pct}% 범위의 신고 거래입니다. 시점수정을 하지 않았고 가격 추정·비교에 사용하지 않습니다.</p>
    {value.per_sqm_median_won != null && <p className="mt-2">㎡당 {manwon(value.per_sqm_min_won ?? 0)}~{manwon(value.per_sqm_max_won ?? 0)} (중앙값 {manwon(value.per_sqm_median_won)})</p>}
    <ul className="mt-2 space-y-1">{value.trades.map(t => <li key={`${t.deal_date}-${t.floor}-${t.area_sqm}-${t.price_won}`}>{t.deal_date} · {t.floor ? `${t.floor}층 · ` : ""}{t.area_sqm}㎡ · {won(t.price_won)}</li>)}</ul>
  </details>;
}

export default function ValuationAssessmentCard({ value }: { value?: ValuationAssessment }) {
  if (!value) return <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">이전 분석 — 공통 평가 기준 적용 여부 미확인. 새 분석으로 현재 자료 조건을 확인해주세요.</p>;
  return <section aria-label="평가 방법과 근거" className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm break-words">
    <h2 className="text-lg font-bold">평가 결과 · {kinds[value.result_kind]}</h2>
    <p>{value.subject.category} · {scopes[value.subject.scope]} · {areas[value.subject.area_basis]}{value.subject.area_sqm != null ? ` ${value.subject.area_sqm}㎡` : ""}</p>
    <p>기준일 {value.subject.as_of_date || "미확인"} · {value.comparison_eligible ? "시장가격 비교용 근거로 제공 — 유효기간·신뢰도 추가 확인" : "시장가격 차이 계산에서 제외"}</p>
    <ul className="space-y-2">{value.methods.map(method => <li key={method.method}><strong>{methods[method.method] || method.method} · {method.status === "selected" ? "사용" : "미사용"}</strong><p className="text-slate-600">{method.reason}</p></li>)}</ul>
    {value.next_actions.length > 0 && <div className="rounded bg-amber-50 p-3 text-amber-900"><h3 className="font-semibold">다음 확인 항목</h3><ul className="mt-2 list-inside list-disc space-y-1">{value.next_actions.map(text => <li key={text}>{text}</li>)}</ul></div>}
    {value.jeonse_context && <JeonseRatio value={value.jeonse_context} />}
    {value.reference_context && value.reference_context.trade_count > 0 && <ReferenceTrades value={value.reference_context} />}
    <details><summary className="cursor-pointer font-semibold">자료 점검과 기준 버전</summary><ul className="mt-2 space-y-2">{value.checks.map(check => <li key={check.code}>{check.status === "available" ? "확인" : "보완 필요"} · {check.message}<span className="block text-xs text-slate-500">{sources[check.source] || check.source} · 자료 기준 {check.reference_date || "미확인"} · 관측 {check.observed_at || "별도 기록 없음"}</span></li>)}</ul><p className="mt-2 text-xs">{value.policy_version} · ML 미사용</p></details>
    {value.limitations.map(text => <p key={text} className="text-xs text-slate-600">{text}</p>)}
  </section>;
}
