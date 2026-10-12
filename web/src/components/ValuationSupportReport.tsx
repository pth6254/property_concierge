"use client";
import Link from "next/link";
import { LandInformationDetails } from "@/components/LandInformationDetails";
import type { ValuationAssessment, ValuationSupportResult } from "@/lib/valuation";
import { DataTable, InfoTable, NumberedList, PastTradeNotice, ReportShell, Sections, type InfoRow } from "@/components/ReportDocument";

/*
 * 보류·조건부 시나리오·공개자료 참고 결과를 시세추정 리포트 문서 양식으로 보여준다.
 * 시장가격을 산출하지 않은 결과에 가격처럼 보이는 숫자를 만들지 않는다. 참고 거래·전세가율은
 * "가격 추정에 사용하지 않음"을 표 제목에 함께 적어 추정가로 오해하지 않게 한다.
 */

const money = (value: number | null | undefined) => value == null ? "미산출" : `${value.toLocaleString("ko-KR")}원`;
const pct = (value: number | null) => value == null ? "미산출" : `${value.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}%`;
const perSqm = (value: number | null | undefined) => value == null ? "—" : `${Math.round(value / 10_000).toLocaleString("ko-KR")}만원/㎡`;

const KINDS: Record<ValuationAssessment["result_kind"], string> = { market_reference: "시장가격 참고", model_estimate: "ML 참고 추정", conditional_scenario: "조건부 시나리오", public_reference: "공개자료 참고", partial_reference: "구성 부분 참고", withheld: "추정 보류", unsupported: "지원 범위 밖" };
const SCOPES: Record<string, string> = { single_unit: "개별 호실", whole_building: "건물 전체", land_and_building: "토지와 건물 전체", single_parcel: "단일 필지", unknown: "미확인" };
const AREAS: Record<string, string> = { exclusive: "전용면적", supply: "공급면적", gross: "연면적", land: "토지면적", unknown: "면적 기준 미확인" };
const SUBTYPES: Record<string, string> = { apartment: "아파트", officetel: "오피스텔", row_house: "연립다세대", detached: "단독·다가구", commercial: "상가", office: "사무실", factory: "공장", warehouse: "창고", land: "토지" };
const TRADES: Record<string, string> = { sale: "매매", jeonse: "전세", rent: "월세", unknown: "미확인" };
const METHODS: Record<string, string> = { sales_comparison: "실거래 비교", income_scenario: "임대료 수익 시나리오", land_public_data: "토지 공개정보", catboost: "CatBoost 가격 모델" };
const LEVELS: Record<string, string> = { A1: "같은 단지 최근 6개월 5건 이상", A2: "같은 단지 최근 12개월 1~4건", A3: "같은 단지 다른 면적 또는 같은 동 유사 단지", A4: "근거 없음" };
const SOURCES: Record<string, string> = { user_input: "사용자 입력", official_data: "공식자료", analysis: "분석 결과", policy: "서비스 기준" };

function ResultBox({ result }: { result: ValuationSupportResult }) {
  const valuation = result.valuation;
  const kind = valuation ? KINDS[valuation.result_kind] : "공통 기준 적용 여부 미확인";
  const scenario = result.income_scenario;
  const reasons = (valuation?.methods ?? []).filter(m => m.status !== "selected").map(m => `${METHODS[m.method] ?? m.method}: ${m.reason}`);
  return (
    <div className="border-2 border-gray-800 mb-4">
      <div className="bg-gray-800 text-white text-center py-2.5">
        <h2 className="text-[13px] tracking-[0.2em]">평가 결과 · {kind}</h2>
      </div>
      <div className="py-6 px-4 text-center">
        {valuation?.result_kind === "model_estimate" && valuation.model_context?.estimated_value != null ? <>
          <p className="text-[11px] tracking-[0.2em] text-gray-500 mb-1">최근 실거래 기준 ML 참고가</p>
          <p className="text-[26px] sm:text-[32px] font-bold text-gray-900 tracking-tight">₩ {valuation.model_context.estimated_value.toLocaleString("ko-KR")} 원</p>
          <p className="text-xs text-gray-600 mt-2">참고 구간 {money(valuation.model_context.value_min)} ~ {money(valuation.model_context.value_max)} · 신뢰도 {valuation.model_context.confidence != null ? `${Math.round(valuation.model_context.confidence * 100)}%` : "미산출"}</p>
          <p className="mt-3 border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] text-amber-900">공개 기준(같은 단지 최근 6개월 5건)에 미달한 근거로 낸 ML 참고 추정입니다. 시장가격 비교·가격 체크리스트 완료에 쓰지 않습니다.</p>
          <div className="mt-2"><PastTradeNotice window={valuation.evidence_window} asOf={valuation.subject.as_of_date} /></div>
        </> : scenario && scenario.scenarios.length > 0 ? <>
          <p className="text-[22px] sm:text-[26px] font-bold text-gray-900">{money(scenario.low_price_won)} ~ {money(scenario.high_price_won)}</p>
          <p className="text-[11px] text-gray-500 mt-2">입력 임대료·운영비·환원율 가정에 따른 조건부 범위이며 시장가격이나 통계적 예측구간이 아닙니다.</p>
        </> : valuation?.result_kind === "public_reference" ? <>
          <p className="text-[22px] font-bold text-gray-900">시장가격 미산출</p>
          <p className="text-[11px] text-gray-500 mt-2">공개자료를 대조한 참고 결과입니다. 시장가격은 산출하지 않습니다.</p>
        </> : <>
          <p className="text-[24px] sm:text-[28px] font-bold text-gray-900 tracking-[0.2em]">추 정 보 류</p>
          <p className="text-[11px] text-gray-500 mt-2">자료·입력 조건을 충족하지 못해 시장가격을 산출하지 않았습니다. 구 평균이나 ML 모델로 대체하지 않습니다.</p>
        </>}
        {reasons.length > 0 && <ul className="mt-4 space-y-1 text-left text-xs text-gray-700">{reasons.map(text => <li key={text}>· {text}</li>)}</ul>}
      </div>
    </div>
  );
}

export default function ValuationSupportReport({ result }: { result: ValuationSupportResult }) {
  const valuation = result.valuation;
  const subject = valuation?.subject;
  const scenario = result.income_scenario;
  const reference = valuation?.reference_context;
  const jeonse = valuation?.jeonse_context;
  const limitations = [...new Set([...(result.limitations ?? []), ...(valuation?.limitations ?? [])])];
  const area = subject?.area_sqm != null ? `${AREAS[subject.area_basis] ?? subject.area_basis} ${subject.area_sqm}㎡ (${(subject.area_sqm / 3.30579).toFixed(2)}평)` : subject ? `${AREAS[subject.area_basis] ?? subject.area_basis} · 면적 미입력` : "";
  const unit = [subject?.dong, subject?.ho].filter(Boolean).join(" / ");

  const subjectRows: InfoRow[] = [
    { divider: "기 본 정 보" },
    ["소  재  지", subject?.address || result.address],
    ...(subject?.building_name ? [["건  물  명", subject.building_name] as InfoRow] : []),
    ["물건 유형", subject ? `${subject.category} · ${SUBTYPES[subject.subtype] ?? subject.subtype}` : result.agent_name],
    ...(subject ? [["거래 유형", TRADES[subject.transaction_type] ?? subject.transaction_type] as InfoRow] : []),
    ...(unit ? [["동  /  호", `${unit} (사용자 입력 · 개별 호실 확인 아님)`] as InfoRow] : []),
    { divider: "평 가 대 상 범 위" },
    ...(subject ? [["평가 범위", SCOPES[subject.scope] ?? subject.scope] as InfoRow, ["면     적", area] as InfoRow] : []),
    { divider: "시 세 추 정 기 본 사 항" },
    ["적용 검토", result.valuation_method],
    ...(subject?.purpose ? [["조 회 목 적", subject.purpose] as InfoRow] : []),
    ["기  준  시  점", subject?.as_of_date || result.as_of_date],
  ];

  const resultRows: InfoRow[] = valuation ? [
    ["결과 종류", KINDS[valuation.result_kind]],
    ["시장가격 비교", valuation.comparison_eligible ? "비교 근거로 제공 — 유효기간·신뢰도 추가 확인" : "시장가격 차이 계산에서 제외"],
    ["ML 모델", valuation.model_status === "used" ? `사용 · ${valuation.model_context?.model ?? ""} (학습 자료 ${valuation.model_context?.trained_through ?? "미상"}까지)` : "미사용"],
    ...(valuation.model_context ? [["근거 단계", `${valuation.model_context.level} · ${LEVELS[valuation.model_context.level] ?? ""}`] as InfoRow, ["근거 내용", valuation.model_context.basis] as InfoRow] : []),
    ["평가 기준", `${valuation.policy_version} · ${valuation.schema_version}`],
  ] : [["평가 기준", "이전 분석 — 공통 평가 기준 적용 여부 미확인. 새 분석으로 현재 자료 조건을 확인해주세요."]];

  return (
    <ReportShell appraisalDate={subject?.as_of_date || result.as_of_date} query={[subject?.address || result.address, subject?.building_name].filter(Boolean).join(" ")} dataSource={["국토교통부 실거래가 공개시스템", ...(result.land_information ? ["VWorld 토지 공개정보"] : [])]}>
      <article aria-label="유형별 검토 결과" className="space-y-9">
        <Sections items={[
          { title: "대상물건 표시 및 내역", body: <InfoTable rows={subjectRows} /> },
          { title: "시세추정 결과", body: <><ResultBox result={result} /><InfoTable rows={resultRows} /></> },
          valuation && valuation.methods.length > 0 && { title: "평가방법 적용 내역", body: (
            <DataTable headers={["평 가 방 법", "적 용", "사 유", "엔 진"]} rows={valuation.methods.map(m => [METHODS[m.method] ?? m.method, m.status === "selected" ? "사용" : "미사용", <span key="r" className="block text-left">{m.reason}</span>, m.engine_version ?? "—"])} />
          ) },
          scenario && { title: "임대 수익 시나리오", body: <div className="space-y-4">
            <p className="border border-amber-300 bg-amber-50 px-4 py-3 text-xs text-amber-900">입력 조건에 따른 시나리오입니다. 환원율은 사용자 가정이며 실측 시장 수익률이나 검증된 시세가 아닙니다.</p>
            <InfoTable rows={[
              ["평가 범위", scenario.inputs.valuation_unit === "single_unit" ? "개별 호실" : "건물 전체"],
              ["현재 받는 월세", money(scenario.inputs.monthly_rent_won)],
              ["월 소유자 운영비 범위", `${money(scenario.inputs.monthly_operating_cost_min_won)} ~ ${money(scenario.inputs.monthly_operating_cost_max_won)}`],
              ["연간 월세 환산액", money(scenario.annual_rent_won)],
              ["연간 순영업소득 범위", `${money(scenario.annual_noi_min_won)} ~ ${money(scenario.annual_noi_max_won)}`],
              ["입력 매매 호가", money(scenario.inputs.asking_price_won)],
              ["호가 대비 총임대수익률", pct(scenario.gross_yield_pct)],
              ["호가 대비 순임대수익률 범위", `${pct(scenario.net_yield_min_pct)} ~ ${pct(scenario.net_yield_max_pct)}`],
            ]} />
            {scenario.scenarios.length > 0 ? <>
              <p className="text-sm font-semibold">조건부 가격 범위: {money(scenario.low_price_won)} ~ {money(scenario.high_price_won)}</p>
              <DataTable caption="환원율 가정별 가격 — 통계적 예측구간이 아닙니다" headers={["환원율 가정", "가격 하한", "가격 상한"]} rows={scenario.scenarios.map(row => [pct(row.cap_rate_pct), money(row.low_price_won), money(row.high_price_won)])} />
            </> : <p role="status" className="font-medium text-amber-800">가격 산출 보류 — 운영비와 순영업소득 조건을 확인해주세요.</p>}
            {!scenario.inputs.asking_price_won && <p className="text-xs">매매 호가를 입력하면 호가 대비 임대수익률도 계산합니다.</p>}
          </div> },
          result.land_information && { title: "토지 공개정보", body: <LandInformationDetails value={result.land_information} /> },
          reference && reference.trade_count > 0 && { title: "참고 실거래 (직접 확인용)", body: <div className="space-y-2">
            <p className="text-[11px] text-gray-500">{reference.complex_name} 최근 {reference.window_months}개월 · 전용면적 ±{reference.area_tolerance_pct}% 범위의 신고 거래 {reference.trade_count}건입니다. 시점수정을 하지 않았고 <strong>가격 추정·비교에 사용하지 않습니다.</strong></p>
            {reference.per_sqm_median_won != null && <p className="text-xs">㎡당 {perSqm(reference.per_sqm_min_won)} ~ {perSqm(reference.per_sqm_max_won)} (중앙값 {perSqm(reference.per_sqm_median_won)})</p>}
            <DataTable headers={["거 래 일", "층", "전용 면적", "거 래 가", "㎡ 당"]} rows={reference.trades.map(t => [t.deal_date, t.floor ? `${t.floor}층` : "—", `${t.area_sqm}㎡`, money(t.price_won), perSqm(t.price_per_sqm_won)])} />
          </div> },
          jeonse && { title: "전세가율 참고", body: <div className="space-y-2">
            <p className="text-[11px] text-gray-500">최근 {jeonse.window_months}개월 {jeonse.complex_name} 전용면적 ±{jeonse.area_tolerance_pct}%의 전세 {jeonse.lease_count}건(갱신 계약 {jeonse.renewal_count}건 포함)과 매매 {jeonse.sale_count}건의 ㎡당 중앙값을 비교했습니다. 시점이 다른 신고를 섞었고 <strong>가격 추정에 사용하지 않습니다.</strong></p>
            <InfoTable rows={[
              ["전세가율", jeonse.ratio_pct != null ? `${jeonse.ratio_pct}%` : "산출 불가"],
              ["전세 ㎡당 중앙값", perSqm(jeonse.lease_per_sqm_median_won)],
              ["매매 ㎡당 중앙값", perSqm(jeonse.sale_per_sqm_median_won)],
            ]} />
            {!jeonse.sufficient && <p className="border border-amber-300 bg-amber-50 px-4 py-2 text-xs text-amber-900">전세 또는 매매 신고가 각 3건 미만이라 참고 수준이 낮습니다. 위험 여부를 판단하지 마세요.</p>}
            {jeonse.missing_months > 0 && <p className="text-xs text-amber-800">전월세 조회를 마치지 못한 달이 {jeonse.missing_months}개월 있습니다.</p>}
            {jeonse.leases.length > 0 && <DataTable headers={["계 약 일", "전용 면적", "보 증 금", "구 분"]} rows={jeonse.leases.map(l => [l.deal_date, `${l.area_sqm}㎡`, money(l.deposit_won), l.renewal ? "갱신" : "신규"])} />}
          </div> },
          valuation && valuation.next_actions.length > 0 && { title: "다음 확인 항목", body: <NumberedList items={valuation.next_actions} /> },
          valuation && valuation.checks.length > 0 && { title: "자료 점검 내역", body: (
            <DataTable headers={["점 검 항 목", "상 태", "자료 기준", "출 처"]} rows={valuation.checks.map(c => [<span key="m" className="block text-left">{c.message}</span>, c.status === "available" ? "확인" : "보완 필요", c.reference_date || "미확인", SOURCES[c.source] ?? c.source])} />
          ) },
          limitations.length > 0 && { title: "제한사항", body: <NumberedList items={limitations} /> },
        ]} />
        <p className="no-print text-sm"><Link href="/appraisal" className="text-primary underline">입력 조건을 바꾸어 다시 검토</Link></p>
      </article>
    </ReportShell>
  );
}
