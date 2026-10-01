"use client";
import Link from "next/link";

/*
 * AppraisalReport — AI 시세추정 리포트 문서 렌더러 (공용)
 *
 * 사용처:
 *   /report      — sessionStorage 결과 (방금 실행한 추정)
 *   /report/[id] — history DB 결과 (저장된 리포트 재열람)
 */

type Comparable = {
  complex_name?: string;
  area_m2?: number;
  deal_price?: number;
  deal_date?: string;
  match_level?: string;
};

type ValuationBreakdown = {
  method: string;
  estimated_value?: number;
  weight?: number;
  note?: string;
};

type AppraisalResult = {
  estimated_price?: number;
  low_price?: number;
  high_price?: number;
  asking_price?: number;
  gap_rate?: number;
  judgement?: string;
  confidence?: number;
  comparables?: Comparable[];
  warnings?: string[];
  data_source?: string[];
  appraisal_date?: string;
  appraisal_purpose?: string;
  land_use_zone?: string;
  official_land_price?: number;
  official_price_ratio?: number;
  build_year?: number;
  exclusive_area_m2?: number;
  common_area_m2?: number;
  total_area_m2?: number;
  jimok?: string;
  road_side?: string;
  valuation_breakdown?: ValuationBreakdown[];
  legal_restrictions?: string[];
  development_plans?: string[];
};

type AnalysisResult = {
  estimated_value?: number;
  cap_rate?: number;
  annual_income?: number;
  roi_5yr?: number;
  investment_grade?: string;
  appraisal_opinion?: string;
  strengths?: string[];
  risk_factors?: string[];
  recommendation?: string;
  price_per_pyeong?: number;
  price_per_sqm?: number;
  area_pyeong?: number;
  regional_avg_per_pyeong?: number;
  comparable_avg?: number;
  comparable_count?: number;
  build_year?: number;
  exclusive_area_m2?: number;
  land_use_zone?: string;
  official_land_price?: number;
  valuation_method?: string;
  legal_restrictions?: string[];
  development_plans?: string[];
  comparables?: Comparable[];
};

const MATCH_LABEL: Record<string, string> = {
  same_complex: "동일 단지",
  same_dong: "동일 동",
  same_gu: "동일 구",
  nearby: "인근",
  fallback: "폴백",
};

function toPyeong(m2: number): string {
  return (m2 / 3.30579).toFixed(2) + "평";
}

function numToKorean(n: number): string {
  if (!n) return "";
  const eok = Math.floor(n / 100_000_000);
  const man = Math.floor((n % 100_000_000) / 10_000);
  const rest = n % 10_000;
  let r = "";
  if (eok > 0) r += `${eok}억`;
  if (man > 0) r += ` ${man.toLocaleString("ko-KR")}만`;
  if (rest > 0) r += ` ${rest.toLocaleString("ko-KR")}`;
  return r.trim() + "원정";
}

function confLabel(c?: number): string {
  if (c == null) return "—";
  const pct = (c * 100).toFixed(0);
  if (c >= 0.80) return `높음 (${pct}%) · 실거래 충분`;
  if (c >= 0.60) return `보통 (${pct}%) · 표본 제한적`;
  if (c >= 0.40) return `낮음 (${pct}%) · 데이터 노후`;
  return `매우 낮음 (${pct}%) · 참고용`;
}

function extractFromReport(report: string, sectionName: string, key: string): string {
  const lines = report.split("\n");
  let inSection = false;
  for (const line of lines) {
    if (line.startsWith("## ") && line.includes(sectionName)) { inSection = true; continue; }
    if (inSection && line.startsWith("## ")) break;
    if (inSection && line.startsWith("| ")) {
      const cells = line.split("|")
        .filter((_, i, a) => i > 0 && i < a.length - 1)
        .map(s => s.replace(/\*\*/g, "").trim());
      if (cells.length >= 2 && cells[0].toLowerCase().includes(key.toLowerCase())) {
        return cells[1].trim();
      }
    }
  }
  return "";
}

function SectionTitle({ number, title }: { number: string; title: string }) {
  return (
    <div className="flex items-baseline gap-3 mb-3 pb-1.5 border-b-2 border-gray-700">
      <span className="text-[11px] font-medium text-gray-500 tracking-wide shrink-0">{number}</span>
      <h2 className="text-sm font-bold text-gray-900 tracking-wide">{title}</h2>
    </div>
  );
}

type InfoRow = [string, string] | { divider: string };

function InfoTable({ rows }: { rows: InfoRow[] }) {
  return (
    <table className="w-full border-collapse text-xs">
      <tbody>
        {rows.map((row, i) => {
          if ("divider" in row) {
            return (
              <tr key={i}>
                <td
                  colSpan={2}
                  className="border border-gray-400 bg-gray-700 text-white px-4 py-1.5 text-center text-[10px] font-semibold tracking-[0.25em]"
                >
                  {row.divider}
                </td>
              </tr>
            );
          }
          const [label, value] = row;
          return (
            <tr key={i}>
              <td className="border border-gray-400 bg-gray-50 px-4 py-2 font-medium text-gray-600 w-[28%] whitespace-nowrap">
                {label}
              </td>
              <td className="border border-gray-400 px-4 py-2 text-gray-800">{value || "—"}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export default function AppraisalReport({
  result,
  query = "",
}: {
  result: Record<string, unknown>;
  query?: string;
}) {
  const ar = (result.analysis_result || {}) as AnalysisResult;
  const ro = result.report_output as { structured?: AppraisalResult } | undefined;
  const ap: AppraisalResult = ro?.structured || {};
  const report = (result.final_report as string) || "";

  /* ── 주소/물건 정보: final_report 마크다운 테이블에서 추출 ── */
  const address      = extractFromReport(report, "대상물 정보", "소재지");
  const buildingName = extractFromReport(report, "대상물 정보", "건물명");
  const propType     = extractFromReport(report, "대상물 정보", "유형");
  const transType    = extractFromReport(report, "대상물 정보", "거래 유형");
  const unitStr      = extractFromReport(report, "대상물 정보", "동");
  const floor        = extractFromReport(report, "대상물 정보", "층수");
  const areaRaw      = extractFromReport(report, "대상물 정보", "전용면적");
  const purpose      = ap.appraisal_purpose || extractFromReport(report, "대상물 정보", "목적");
  const methodStr    = ar.valuation_method
    || extractFromReport(report, "대상물 정보", "산정 방식")
    || extractFromReport(report, "대상물 정보", "평가 기준"); // 구버전 리포트 호환

  const appraisalDate =
    ap.appraisal_date ||
    extractFromReport(report, "대상물 정보", "기준시점") ||
    new Date().toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
  const today = new Date().toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });

  const buildYear   = ar.build_year   || ap.build_year;
  const landUseZone = ar.land_use_zone || ap.land_use_zone;
  const officialLp  = ar.official_land_price || ap.official_land_price;
  const legalItems  = ap.legal_restrictions?.length ? ap.legal_restrictions : (ar.legal_restrictions || []);
  const devPlans    = ap.development_plans?.length  ? ap.development_plans  : (ar.development_plans  || []);
  const comparables = ap.comparables?.length ? ap.comparables : (ar.comparables || []);

  /* ── 면적 계산 ── */
  const exclusiveM2 = ap.exclusive_area_m2 || ar.exclusive_area_m2 || 0;
  const commonM2    = ap.common_area_m2 || 0;
  const totalM2     = ap.total_area_m2 || (exclusiveM2 && commonM2 ? exclusiveM2 + commonM2 : 0);
  const areaPyeong  = ar.area_pyeong || (exclusiveM2 ? exclusiveM2 / 3.30579 : 0);

  /* 전용면적 표시 문자열 */
  const exclusiveAreaStr = exclusiveM2
    ? `${exclusiveM2.toFixed(2)}㎡ (${toPyeong(exclusiveM2)})`
    : areaRaw || "—";

  /* ── 건물 노후도 ── */
  const currentYear = new Date().getFullYear();
  const buildAgeStr = buildYear
    ? `${buildYear}년 준공 (경과 ${currentYear - buildYear}년)`
    : "";

  /* ── 공시가격 추정액 (공시지가 × 전용면적) ── */
  const officialTotalManwon =
    officialLp && exclusiveM2
      ? Math.round((officialLp * exclusiveM2) / 10_000)
      : 0;

  /* ── 대상물건 정보 행 (그룹 구분선 포함) ── */
  const propRows: InfoRow[] = [
    /* 기본 식별 정보 */
    { divider: "기 본 정 보" },
    ...(address      ? [["소  재  지", address]          as [string, string]] : []),
    ...(buildingName ? [["건  물  명", buildingName]      as [string, string]] : []),
    ...(propType     ? [["물건 유형",  propType]          as [string, string]] : []),
    ...(transType    ? [["거래 유형",  transType]         as [string, string]] : []),
    ...(unitStr      ? [["동  /  호",  unitStr]           as [string, string]] : []),
    ...(floor        ? [["층     수",  floor]             as [string, string]] : []),

    /* 면적 */
    { divider: "면 적 정 보" },
    ["전 용 면 적", exclusiveAreaStr],
    ...(commonM2     ? [["공 용 면 적", `${commonM2.toFixed(2)}㎡ (${toPyeong(commonM2)})`]   as [string, string]] : []),
    ...(totalM2      ? [["계 약 면 적", `${totalM2.toFixed(2)}㎡ (${toPyeong(totalM2)})`]     as [string, string]] : []),
    ...(areaPyeong && !exclusiveM2
      ? [["전용면적(평)", `${areaPyeong.toFixed(2)}평`] as [string, string]]
      : []),

    /* 건물 정보 */
    { divider: "건 물 정 보" },
    ...(buildAgeStr  ? [["건  축  연  도", buildAgeStr]   as [string, string]] : []),

    /* 토지·공법 정보 */
    { divider: "토 지 · 공 법 정 보" },
    ...(landUseZone  ? [["용  도  지  역", landUseZone]                                              as [string, string]] : []),
    ...(ap.jimok     ? [["지       목",   ap.jimok]                                                  as [string, string]] : []),
    ...(ap.road_side ? [["도  로  접  면", ap.road_side]                                             as [string, string]] : []),
    ...(officialLp   ? [["공  시  지  가", `${officialLp.toLocaleString("ko-KR")}원/㎡`]             as [string, string]] : []),
    ...(officialTotalManwon
      ? [["공시가격 추정액", `약 ${officialTotalManwon.toLocaleString("ko-KR")}만원 (전용면적 기준)`] as [string, string]]
      : []),

    /* 시세추정 기본사항 */
    { divider: "시 세 추 정 기 본 사 항" },
    ...(purpose     ? [["조 회 목 적",   purpose]         as [string, string]] : []),
    ...(methodStr   ? [["산 정 방 식",   methodStr]       as [string, string]] : []),
    ["기  준  시  점", appraisalDate],
  ];

  /* ── 추정 시세 세부 행 ── */
  const valueRows: InfoRow[] = [
    ["추 정 범 위",
      ap.low_price && ap.high_price
        ? `${ap.low_price.toLocaleString("ko-KR")}원  ~  ${ap.high_price.toLocaleString("ko-KR")}원`
        : "—"],
    ["평 당 가",
      ar.price_per_pyeong ? `${(ar.price_per_pyeong * 10_000).toLocaleString("ko-KR")}원/평` : "—"],
    ...(ar.price_per_sqm
      ? [["㎡ 당 단 가", `${(ar.price_per_sqm * 10_000).toLocaleString("ko-KR")}원/㎡`] as [string, string]]
      : []),
    ["지역 평균 평당가",
      ar.regional_avg_per_pyeong ? `${(ar.regional_avg_per_pyeong * 10_000).toLocaleString("ko-KR")}원/평` : "—"],
    ...(ar.comparable_avg && ar.comparable_count
      ? [["인근 실거래 평균", `${(ar.comparable_avg * 10_000).toLocaleString("ko-KR")}원 (${ar.comparable_count}건)`] as [string, string]]
      : []),
    ...(ap.official_price_ratio
      ? [["공시가격 대비", `공시가 기준 추정액의 ${ap.official_price_ratio.toFixed(1)}배`] as [string, string]]
      : []),
    ...(ap.asking_price
      ? [["호 가", `${ap.asking_price.toLocaleString("ko-KR")}원`] as [string, string]]
      : []),
    ...(ap.gap_rate != null
      ? [["괴리율 (호가 대비)", `${(ap.gap_rate * 100).toFixed(1)}%`] as [string, string]]
      : []),
    ["평가 신뢰도", confLabel(ap.confidence)],
    ...(ap.judgement
      ? [["고저평가 판단", ap.judgement] as [string, string]]
      : []),
  ];

  /* ── 산정방법별 추정가 데이터 ── */
  const breakdownRows =
    ap.valuation_breakdown && ap.valuation_breakdown.length > 0
      ? ap.valuation_breakdown
      : methodStr && ap.estimated_price
      ? [{ method: methodStr, estimated_value: ap.estimated_price, weight: 1.0, note: confLabel(ap.confidence) }]
      : [];

  return (
    <div className="report-wrapper min-h-screen bg-slate-300 py-6 px-4">

      {/* ── 상단 툴바 (인쇄 시 숨김) ── */}
      <div className="no-print max-w-[880px] mx-auto mb-4 flex justify-between items-center">
        <Link href="/appraisal" className="text-sm text-primary-strong hover:underline font-medium">
          ← 새 시세추정
        </Link>
        <button
          onClick={() => window.print()}
          className="px-4 py-2 bg-gray-800 text-white text-sm rounded hover:bg-gray-900 transition-colors"
        >
          인쇄 / PDF 저장
        </button>
      </div>

      {/* ─────────────────── 문서 본체 ─────────────────── */}
      <div
        id="appraisal-doc"
        className="max-w-[880px] mx-auto bg-white shadow-2xl"
        style={{ fontFamily: "'Malgun Gothic', 'Apple SD Gothic Neo', '맑은 고딕', sans-serif" }}
      >

        {/* ── 표지 헤더 ── */}
        <div className="border-b-4 border-double border-gray-800 px-14 pt-12 pb-8 text-center">
          <p className="text-[10px] tracking-[0.5em] text-gray-400 mb-2 uppercase">
            AI Automated Valuation Report
          </p>
          <h1 className="text-[28px] font-bold tracking-[0.15em] text-gray-900 mb-2">
            부동산 AI 시세추정 리포트
          </h1>
          <p className="text-[11px] text-gray-400 mb-5">
            본 리포트는 자동가치산정(AVM) 기반 시세 추정 자료이며, 「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가서가 아닙니다.
          </p>
          <div className="inline-flex gap-10 border border-gray-300 bg-gray-50 px-8 py-3 text-xs text-gray-600">
            <div className="flex gap-2">
              <span className="text-gray-400">기 준 시 점</span>
              <span className="font-semibold text-gray-800">{appraisalDate}</span>
            </div>
            <div className="flex gap-2">
              <span className="text-gray-400">발 행 일 자</span>
              <span className="font-semibold text-gray-800">{today}</span>
            </div>
          </div>
          {query && (
            <p className="mt-4 text-xs text-gray-400">조회 내용: {query}</p>
          )}
        </div>

        {/* ── 본문 ── */}
        <div className="px-14 py-10 space-y-9">

          {/* ── 제 1 절: 대상물건 표시 및 내역 ── */}
          {propRows.length > 0 && (
            <section>
              <SectionTitle number="제 1 절" title="대상물건 표시 및 내역" />
              <InfoTable rows={propRows} />
            </section>
          )}

          {/* ── 제 2 절: AI 추정 시세 ── */}
          <section>
            <SectionTitle number="제 2 절" title="AI 추정 시세" />

            {/* 추정 시세 대형 표시 */}
            <div className="border-2 border-gray-800 mb-4">
              <div className="bg-gray-800 text-white text-center py-2.5">
                <span className="text-[11px] tracking-[0.35em]">추 정 시 장 가 치 (Estimated Market Value)</span>
              </div>
              <div className="py-7 text-center">
                <p className="text-[32px] font-bold text-gray-900 tracking-tight">
                  {ap.estimated_price
                    ? `₩ ${ap.estimated_price.toLocaleString("ko-KR")} 원`
                    : "—"}
                </p>
                {ap.estimated_price && (
                  <p className="text-[11px] text-gray-400 mt-2">
                    ( {numToKorean(ap.estimated_price)} )
                  </p>
                )}
              </div>
            </div>

            <InfoTable rows={valueRows} />
          </section>

          {/* ── 제 3 절: 산정방법별 추정가 ── */}
          {breakdownRows.length > 0 && (
            <section>
              <SectionTitle number="제 3 절" title="산정방법별 추정가" />
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr>
                    {["평 가 방 법", "시 산 가 액", "가 중 치", "비 고"].map(h => (
                      <th key={h} className="border border-gray-400 bg-gray-100 px-4 py-2.5 text-center font-semibold text-gray-700">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {breakdownRows.map((b, i) => (
                    <tr key={i}>
                      <td className="border border-gray-400 px-4 py-2.5 text-center">{b.method}</td>
                      <td className="border border-gray-400 px-4 py-2.5 text-right font-medium">
                        {b.estimated_value ? `${b.estimated_value.toLocaleString("ko-KR")}원` : "—"}
                      </td>
                      <td className="border border-gray-400 px-4 py-2.5 text-center">
                        {b.weight != null ? `${(b.weight * 100).toFixed(0)}%` : "—"}
                      </td>
                      <td className="border border-gray-400 px-4 py-2.5 text-gray-600">{b.note || ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {/* ── 제 4 절: 투자 수익성 분석 ── */}
          {(ar.cap_rate != null || ar.annual_income || ar.roi_5yr != null || ar.investment_grade) && (
            <section>
              <SectionTitle number="제 4 절" title="투자 수익성 분석" />
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr>
                    {["Cap Rate", "연 임대수입 추정", "5년 예상 수익률", "투 자 등 급"].map(h => (
                      <th key={h} className="border border-gray-400 bg-gray-100 px-4 py-2.5 text-center font-semibold text-gray-700">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="border border-gray-400 px-4 py-4 text-center text-lg font-bold text-gray-900">
                      {ar.cap_rate != null ? `${ar.cap_rate}%` : "—"}
                    </td>
                    <td className="border border-gray-400 px-4 py-4 text-center text-base font-bold text-gray-900">
                      {ar.annual_income ? `${(ar.annual_income * 10_000).toLocaleString("ko-KR")}원` : "—"}
                    </td>
                    <td className="border border-gray-400 px-4 py-4 text-center text-lg font-bold text-gray-900">
                      {ar.roi_5yr != null ? `${ar.roi_5yr}%` : "—"}
                    </td>
                    <td className="border border-gray-400 px-4 py-4 text-center text-base font-bold text-gray-900">
                      {ar.investment_grade || "—"}
                    </td>
                  </tr>
                </tbody>
              </table>
            </section>
          )}

          {/* ── 제 5 절: 비교 사례 분석 ── */}
          {comparables.length > 0 && (
            <section>
              <SectionTitle number="제 5 절" title="비교 사례 분석" />
              <p className="text-[11px] text-gray-500 mb-2">
                총 {comparables.length}건의 실거래 사례를 수집하여 비교·분석하였습니다.
              </p>
              <table className="w-full border-collapse text-xs">
                <thead>
                  <tr>
                    {["단 지 명", "전용 면적", "거 래 가", "거 래 일", "매 칭 수 준"].map(h => (
                      <th key={h} className="border border-gray-400 bg-gray-100 px-3 py-2.5 text-center font-semibold text-gray-700">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {comparables.map((c, i) => (
                    <tr key={i} className={i % 2 === 1 ? "bg-slate-50" : ""}>
                      <td className="border border-gray-400 px-3 py-2">{c.complex_name || "—"}</td>
                      <td className="border border-gray-400 px-3 py-2 text-center">
                        {c.area_m2 ? `${c.area_m2.toFixed(1)}㎡` : "—"}
                      </td>
                      <td className="border border-gray-400 px-3 py-2 text-right">
                        {c.deal_price ? `${c.deal_price.toLocaleString("ko-KR")}원` : "—"}
                      </td>
                      <td className="border border-gray-400 px-3 py-2 text-center">{c.deal_date || "—"}</td>
                      <td className="border border-gray-400 px-3 py-2 text-center">
                        {MATCH_LABEL[c.match_level || ""] || c.match_level || "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          )}

          {/* ── 제 6 절: 공법상 제한사항 및 인근 개발계획 ── */}
          {(legalItems.length > 0 || devPlans.length > 0) && (
            <section>
              <SectionTitle number="제 6 절" title="공법상 제한사항 및 인근 개발계획" />
              <div className="space-y-4">
                {legalItems.length > 0 && (
                  <div>
                    <p className="text-[11px] font-bold text-gray-700 mb-2">① 공법상 제한사항</p>
                    <table className="w-full border-collapse text-xs">
                      <tbody>
                        {legalItems.map((item, i) => (
                          <tr key={i}>
                            <td className="border border-gray-300 bg-gray-50 px-3 py-2 w-8 text-center text-gray-500 shrink-0">
                              {i + 1}
                            </td>
                            <td className="border border-gray-300 px-4 py-2 text-gray-800">{item}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {devPlans.length > 0 && (
                  <div>
                    <p className="text-[11px] font-bold text-gray-700 mb-2">② 인근 개발계획</p>
                    <table className="w-full border-collapse text-xs">
                      <tbody>
                        {devPlans.map((item, i) => (
                          <tr key={i}>
                            <td className="border border-gray-300 bg-gray-50 px-3 py-2 w-8 text-center text-gray-500 shrink-0">
                              {i + 1}
                            </td>
                            <td className="border border-gray-300 px-4 py-2 text-gray-800">{item}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </section>
          )}

          {/* ── 제 7 절: AI 분석 의견 ── */}
          {(ar.appraisal_opinion || ar.strengths?.length || ar.risk_factors?.length || ar.recommendation) && (
            <section>
              <SectionTitle number="제 7 절" title="AI 분석 의견" />

              {ar.appraisal_opinion && (
                <div className="border border-gray-400 bg-gray-50 px-5 py-4 mb-5 text-xs leading-relaxed text-gray-800">
                  {ar.appraisal_opinion}
                </div>
              )}

              {(ar.strengths?.length || ar.risk_factors?.length) ? (
                <div className="grid grid-cols-2 gap-4 mb-5">
                  {ar.strengths && ar.strengths.length > 0 && (
                    <div className="border border-gray-300">
                      <div className="bg-gray-100 border-b border-gray-300 px-4 py-2">
                        <p className="text-[11px] font-bold text-gray-700 tracking-wide">가 치 상 승 요 인</p>
                      </div>
                      <ol className="px-5 py-3 space-y-1.5 list-decimal list-outside text-xs text-gray-800 ml-3">
                        {ar.strengths.map((s, i) => <li key={i}>{s}</li>)}
                      </ol>
                    </div>
                  )}
                  {ar.risk_factors && ar.risk_factors.length > 0 && (
                    <div className="border border-gray-300">
                      <div className="bg-gray-100 border-b border-gray-300 px-4 py-2">
                        <p className="text-[11px] font-bold text-gray-700 tracking-wide">리 스 크 요 인</p>
                      </div>
                      <ol className="px-5 py-3 space-y-1.5 list-decimal list-outside text-xs text-gray-800 ml-3">
                        {ar.risk_factors.map((r, i) => <li key={i}>{r}</li>)}
                      </ol>
                    </div>
                  )}
                </div>
              ) : null}

              {ar.recommendation && (
                <table className="w-full border-collapse text-xs">
                  <tbody>
                    <tr>
                      <td className="border-2 border-gray-800 bg-gray-800 text-white px-5 py-3 font-bold text-center w-[22%] tracking-[0.2em] align-middle">
                        종합의견
                      </td>
                      <td className="border-2 border-gray-800 px-5 py-3 font-semibold text-sm text-gray-900">
                        {ar.recommendation}
                      </td>
                    </tr>
                  </tbody>
                </table>
              )}
            </section>
          )}

          {/* ── 주의사항 ── */}
          {ap.warnings && ap.warnings.length > 0 && (
            <div className="border border-amber-400 bg-amber-50 px-5 py-4">
              <p className="text-[11px] font-bold text-amber-800 mb-2">⚠ 주의사항</p>
              {ap.warnings.map((w, i) => (
                <p key={i} className="text-xs text-amber-800">{i + 1}. {w}</p>
              ))}
            </div>
          )}

          {/* ── 하단 고지사항 ── */}
          <div className="border-t-2 border-gray-800 pt-6 mt-4">
            <div className="text-[10px] text-gray-400 leading-[1.8]">
              <p className="font-semibold text-gray-500 mb-1.5">【 고 지 사 항 】</p>
              <p>
                1. 본 리포트는 공개 데이터 기반 자동가치산정 모형(AVM, Automated Valuation Model)이
                산출한 <span className="font-semibold text-gray-500">참고용 시세 추정 자료</span>이며,
                「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아니고 법적 효력이 없습니다.
              </p>
              <p>
                2. 담보 설정·소송·과세 등 법적 효력이 필요한 가치 판단은 국가자격을 보유한
                감정평가사에게 의뢰하시기 바랍니다.
              </p>
              <p>
                3. 추정 시세는 데이터 상황에 따라 실제 거래 가능 가격과 차이가 있을 수 있으며,
                본 리포트를 근거로 한 의사결정의 책임은 이용자에게 있습니다.
              </p>
              {ap.data_source && ap.data_source.length > 0 && (
                <p className="mt-2">데이터 출처: {ap.data_source.join(" · ")}</p>
              )}
            </div>
          </div>

        </div>
      </div>
    </div>
  );
}
