import Link from "next/link";
import { LandInformationDetails } from "@/components/LandInformationDetails";
import type { ValuationSupportResult } from "@/lib/valuation";
import ValuationAssessmentCard from "@/components/ValuationAssessmentCard";

const money = (value: number | null) => value == null ? "미산출" : `${value.toLocaleString("ko-KR")}원`;
const pct = (value: number | null) => value == null ? "미산출" : `${value.toLocaleString("ko-KR", { maximumFractionDigits: 4 })}%`;

export default function ValuationSupportReport({ result }: { result: ValuationSupportResult }) {
  const scenario = result.income_scenario;
  return <article className="mx-auto max-w-3xl space-y-5 rounded-xl bg-white p-4 shadow sm:p-8" aria-label="유형별 검토 결과">
    <h1 className="text-2xl font-bold">{result.valuation_method}</h1>
    <p>{result.address} · {result.agent_name}</p><p className="text-sm text-slate-500">분석 기준일 {result.as_of_date}</p>
    <ValuationAssessmentCard value={result.valuation} />
    {scenario && <>
      <p className="rounded-lg bg-amber-50 p-3 text-sm text-amber-900">입력 조건에 따른 시나리오입니다. 환원율은 사용자 가정이며 실측 시장 수익률이나 검증된 시세가 아닙니다.</p>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt>평가 범위</dt><dd>{scenario.inputs.valuation_unit === "single_unit" ? "개별 호실" : "건물 전체"}</dd>
        <dt>현재 받는 월세</dt><dd>{money(scenario.inputs.monthly_rent_won)}</dd>
        <dt>월 소유자 운영비 범위</dt><dd>{money(scenario.inputs.monthly_operating_cost_min_won)} ~ {money(scenario.inputs.monthly_operating_cost_max_won)}</dd>
        <dt>연간 월세 환산액</dt><dd>{money(scenario.annual_rent_won)}</dd>
        <dt>연간 순영업소득 범위</dt><dd>{money(scenario.annual_noi_min_won)} ~ {money(scenario.annual_noi_max_won)}</dd>
        <dt>입력 매매 호가</dt><dd>{money(scenario.inputs.asking_price_won)}</dd>
        <dt>호가 대비 총임대수익률</dt><dd>{pct(scenario.gross_yield_pct)}</dd>
        <dt>호가 대비 순임대수익률 범위</dt><dd>{pct(scenario.net_yield_min_pct)} ~ {pct(scenario.net_yield_max_pct)}</dd>
      </dl>
      {scenario.scenarios.length > 0 ? <>
        <p className="text-lg font-semibold">조건부 가격 범위: {money(scenario.low_price_won)} ~ {money(scenario.high_price_won)}</p>
        <div className="overflow-x-auto"><table className="w-full text-right text-sm"><caption className="mb-2 text-left text-slate-600">환원율 가정별 가격 — 통계적 예측구간이 아닙니다</caption>
          <thead><tr className="border-b"><th className="p-2">환원율 가정</th><th className="p-2">가격 하한</th><th className="p-2">가격 상한</th></tr></thead>
          <tbody>{scenario.scenarios.map(row => <tr key={row.cap_rate_pct} className="border-b"><td className="p-2">{pct(row.cap_rate_pct)}</td><td className="p-2">{money(row.low_price_won)}</td><td className="p-2">{money(row.high_price_won)}</td></tr>)}</tbody>
        </table></div>
      </> : <p role="status" className="font-medium text-amber-800">가격 산출 보류 — 운영비와 순영업소득 조건을 확인해주세요.</p>}
      {!scenario.inputs.asking_price_won && <p className="text-sm">매매 호가를 입력하면 호가 대비 임대수익률도 계산합니다.</p>}
    </>}
    {result.land_information && <LandInformationDetails value={result.land_information} />}
    <ul className="space-y-2 text-sm text-slate-600">{result.limitations.map(text => <li key={text}>{text}</li>)}</ul>
    <p className="text-sm">AVM 기반 참고용 분석이며 「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아닙니다.</p>
    <Link href="/appraisal" className="inline-block text-primary underline">입력 조건을 바꾸어 다시 검토</Link>
  </article>;
}
