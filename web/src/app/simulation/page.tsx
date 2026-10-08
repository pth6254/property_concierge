"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { removeSessionValue, useSessionValue } from "@/lib/sessionStore";
import type { SimulationResult, SimulationRequest, ScenarioResult } from "@/lib/types";

const PROP_TYPES   = ["아파트", "연립다세대", "단독다가구", "오피스텔", "상가", "사무실", "오피스", "공장", "창고", "토지"];
const REPAY_TYPES  = [
  { value: "equal_payment",   label: "원리금균등상환" },
  { value: "equal_principal", label: "원금균등상환" },
  { value: "interest_only",   label: "만기일시상환" },
];
const RENTAL_MODES = ["없음", "전세", "월세", "임차인 승계"];

function parsePrice(s: string): number {
  if (!s.trim()) return 0;
  const value = s.replace(/[\s,]/g, "").replace(/원$/, "");
  if (/^\d+$/.test(value)) return Number(value);
  const match = /^(?:(\d+(?:\.\d+)?)억)?(?:(\d+(?:\.\d+)?)천만)?(?:(\d+(?:\.\d+)?)만)?$/.exec(value);
  if (!match || !match[0]) return NaN;
  const total = Number(match[1] ?? 0) * 100000000 + Number(match[2] ?? 0) * 10000000 + Number(match[3] ?? 0) * 10000;
  return Number.isSafeInteger(total) ? total : NaN;
}

function fmt(n?: number) { return n != null ? n.toLocaleString("ko-KR") + "원" : "—"; }
function fmtPct(n?: number, deci = 2) { return n != null ? (n >= 0 ? "+" : "") + n.toFixed(deci) + "%" : "—"; }
function signLabel(n?: number) { return n == null ? "—" : n > 0 ? "▲" : n < 0 ? "▼" : "─"; }

/** 추천·비교 페이지에서 "시뮬레이션 해보기"로 넘길 때 실어 보내는 매물 정보 */
type ListingSeed = {
  asking_price?: number | null;
  property_type?: string;
  deposit_price?: number;
  maintenance_fee?: number;
  case_id?: number;
  candidate_id?: number;
  inputs?: Partial<SimulationRequest>;
  profile_inputs?: Partial<SimulationRequest>;
  input_source?: "saved" | "profile";
  home_count_basis?: "after_purchase";
};

const LISTING_TYPE_TO_PROP: Record<string, string> = {
  apartment: "아파트", officetel: "오피스텔", land: "토지",
  row_house: "연립다세대", detached: "단독다가구",
  non_residential: "상가", industrial: "공장",
  주거용: "아파트", 상업용: "상가", 업무용: "오피스", 산업용: "공장",
};

/**
 * 넘겨받은 매물 정보를 폼의 초기값으로 주입한다.
 *
 * 이전에는 폼이 마운트된 뒤 useEffect 에서 sessionStorage 를 읽어 각 입력을
 * setState 로 채웠는데, 그건 effect 안의 동기 setState 라 연쇄 렌더를 유발한다
 * (react-hooks/set-state-in-effect).
 *
 * 대신 시드를 key 로 넘겨, 클라이언트에서 시드가 확인되는 순간 폼이 새로
 * 마운트되며 useState 초기값으로 반영되게 한다. 서버 렌더 시점에는 시드가
 * undefined 라 기본값 폼이 그대로 그려지므로(게이트로 페이지를 비우지 않는다)
 * 초기 페인트가 비지 않는다.
 */
export default function SimulationPage() {
  const rawSeed = useSessionValue("simFromListing");
  const seed = rawSeed ?? null;
  const cleanupTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    if (cleanupTimer.current !== null) clearTimeout(cleanupTimer.current);
    // StrictMode의 effect 재실행과 폼의 key 변경을 실제 페이지 이탈로 오인하지 않는다.
    return () => { cleanupTimer.current = setTimeout(() => removeSessionValue("simFromListing"), 0); };
  }, []);
  return <SimulationForm key={seed ?? "no-seed"} rawSeed={seed} />;
}

function SimulationForm({ rawSeed }: { rawSeed: string | null }) {
  const seed = useMemo<ListingSeed>(
    () => (rawSeed ? (JSON.parse(rawSeed) as ListingSeed) : {}),
    [rawSeed],
  );

  // 입력 상태
  const [purchasePriceStr, setPurchasePriceStr] = useState(
    seed.asking_price ? (seed.asking_price % 10000 === 0 ? `${seed.asking_price / 10000}만` : String(seed.asking_price)) : "",
  );
  const [propType, setPropType]     = useState(
    seed.property_type
      ? (LISTING_TYPE_TO_PROP[seed.property_type] ?? seed.property_type)
      : "아파트",
  );
  const previous = seed.inputs;
  const [loanRatio, setLoanRatio]   = useState((previous?.loan_ratio ?? 0.5) * 100);
  const [interestRate, setInterestRate] = useState(previous?.annual_interest_rate ?? 4.0);
  const [loanYears, setLoanYears]   = useState(previous?.loan_years ?? 30);
  const [repayType, setRepayType]   = useState<string>(previous?.repayment_type ?? "equal_payment");
  const [holdingYears, setHoldingYears] = useState(previous?.holding_years ?? 3);
  const [growthRate, setGrowthRate] = useState(previous?.expected_annual_growth_rate ?? 0);
  // 전세 보증금이 있는 매물이면 임대 모드를 전세로 맞춰서 시작한다
  const [rentalMode, setRentalMode] = useState(previous?.assumed_deposit ? "임차인 승계" : previous?.rent_fee ? "월세" : (previous?.rent_deposit ?? seed.deposit_price) ? "전세" : "없음");
  const [assumedStr, setAssumedStr] = useState(String(previous?.assumed_deposit ?? ""));
  const [depositStr, setDepositStr] = useState(
    String(previous?.rent_deposit ?? seed.deposit_price ?? ""),
  );
  const [rentFeeStr, setRentFeeStr] = useState(String(previous?.rent_fee ?? ""));
  const [mgmtFeeStr, setMgmtFeeStr] = useState(
    String(previous?.monthly_management_fee ?? seed.maintenance_fee ?? ""),
  );
  const [ownedHomes, setOwnedHomes] = useState(previous?.owned_homes ?? 1);

  // 세금·규제 입력
  const [annualIncomeStr, setAnnualIncomeStr] = useState(String(previous?.annual_income ?? ""));
  const [cashStr, setCashStr] = useState(String(previous?.cash_available ?? ""));
  const [paymentLimitStr, setPaymentLimitStr] = useState(String(previous?.monthly_payment_limit ?? ""));
  const [existingPaymentStr, setExistingPaymentStr] = useState(String(previous?.existing_loan_annual_payment ?? ""));
  const [vacancyRate, setVacancyRate] = useState(previous?.vacancy_rate ?? 5);
  const [adjustedArea, setAdjustedArea] = useState(previous?.adjusted_area ?? false);
  const [officialPriceStr, setOfficialPriceStr] = useState(String(previous?.official_price ?? ""));

  const [rateSource, setRateSource] = useState("");             // ECOS 금리 출처

  const [result, setResult] = useState<SimulationResult | null>(null);
  const [report, setReport] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]   = useState("");
  const [tab, setTab]       = useState(0);
  const [profileApplied, setProfileApplied] = useState(false);

  const applyProfile = () => {
    const inputs = seed.profile_inputs;
    if (!inputs) return;
    setCashStr(String(inputs.cash_available ?? ""));
    setPaymentLimitStr(String(inputs.monthly_payment_limit ?? ""));
    setAnnualIncomeStr(String(inputs.annual_income ?? ""));
    setExistingPaymentStr(String(inputs.existing_loan_annual_payment ?? ""));
    setLoanRatio((inputs.loan_ratio ?? 0.5) * 100);
    setInterestRate(inputs.annual_interest_rate ?? 4);
    setLoanYears(inputs.loan_years ?? 30);
    setOwnedHomes(inputs.owned_homes ?? 1);
    setAdjustedArea(inputs.adjusted_area ?? false);
    setRepayType("equal_payment");
    setRateSource("");
    setResult(null); setReport(""); setError("");
    setProfileApplied(true);
  };

  // 최신 주담대 평균금리 자동 세팅 (한국은행 ECOS)
  useEffect(() => {
    let cancelled = false;
    api.marketRate()
      .then(r => {
        if (!cancelled && !profileApplied && r.is_live && previous?.annual_interest_rate == null) {
          setInterestRate(r.rate);
          setRateSource(r.source);
        }
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [previous?.annual_interest_rate, profileApplied]);

  // (넘겨받은 매물 정보는 위 useState 초기값으로 이미 반영돼 있다)

  const handleSubmit = async () => {
    const purchasePrice = parsePrice(purchasePriceStr);
    if (!purchasePrice) { setError("매수가를 입력해주세요."); return; }
    if (!Number.isInteger(ownedHomes) || ownedHomes < 1 || ownedHomes > 100) {
      setError("취득 후 주택 수는 1~100의 정수로 입력해주세요. 첫 주택 취득은 1입니다."); return;
    }
    if ([cashStr, paymentLimitStr, existingPaymentStr, annualIncomeStr, officialPriceStr, depositStr]
      .some(value => value.trim() !== "" && !Number.isSafeInteger(parsePrice(value)))) {
      setError("금액은 150000000, 1.5억, 1억 5000만처럼 입력해주세요."); return;
    }
    setError("");
    setLoading(true);
    try {
      const params: SimulationRequest = {
        case_id: seed.case_id,
        candidate_id: seed.candidate_id,
        purchase_price: purchasePrice,
        cash_available: cashStr ? parsePrice(cashStr) : undefined,
        monthly_payment_limit: paymentLimitStr ? parsePrice(paymentLimitStr) : undefined,
        existing_loan_annual_payment: existingPaymentStr ? parsePrice(existingPaymentStr) : 0,
        loan_ratio: loanRatio / 100,
        annual_interest_rate: interestRate,
        loan_years: loanYears,
        repayment_type: repayType as SimulationRequest["repayment_type"],
        holding_years: holdingYears,
        expected_annual_growth_rate: growthRate,
        property_type: propType,
        owned_homes: ownedHomes,
        rent_deposit: rentalMode === "전세" && depositStr ? parsePrice(depositStr) : undefined,
        assumed_deposit: rentalMode === "임차인 승계" && assumedStr ? parsePrice(assumedStr) : undefined,
        rent_fee: rentalMode === "월세" && rentFeeStr ? parseInt(rentFeeStr) : undefined,
        monthly_management_fee: mgmtFeeStr ? parseInt(mgmtFeeStr) : undefined,
        official_price: officialPriceStr ? parsePrice(officialPriceStr) : undefined,
        vacancy_rate: vacancyRate,
        adjusted_area: adjustedArea,
        annual_income: annualIncomeStr ? parsePrice(annualIncomeStr) : undefined,
      };
      const res = await api.simulation(params) as { result?: SimulationResult; report?: string; error?: string };
      if (res.error) throw new Error(res.error);
      setResult(res.result || null);
      setReport(res.report || "");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "시뮬레이션 실패");
    } finally {
      setLoading(false);
    }
  };

  const verdictStyle = (aroi?: number) => {
    if (!aroi) return "bg-gray-100 text-gray-700";
    if (aroi >= 10) return "bg-green-100 text-green-700";
    if (aroi >= 5)  return "bg-yellow-100 text-yellow-700";
    if (aroi >= 0)  return "bg-orange-100 text-orange-700";
    return "bg-red-100 text-red-700";
  };

  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-1">투자 시뮬레이션</h1>
      <p className="text-slate-500 text-sm mb-5">부동산 투자 조건을 입력하면 수익성을 계산합니다.</p>
      <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-3 py-2 rounded-lg mb-5">
        ⚠️ 이 시뮬레이션은 간이 계산입니다. 실제 세율·대출 조건은 다를 수 있습니다.
      </p>
      {seed.case_id && seed.input_source && <div className="mb-5 rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm">
        <p>{seed.input_source === "saved" && !profileApplied ? "이 후보에 저장된 분석 조건으로 입력을 채웠습니다." : "케이스 공통 매수 조건으로 입력을 채웠습니다. 매수에 쓸 현금은 비상자금을 제외한 금액입니다."}</p>
        {seed.input_source === "saved" && !seed.home_count_basis && !profileApplied && <p className="mt-2 text-amber-800">이전 분석에는 주택 수 기준이 기록되지 않았습니다. 이번 취득을 포함한 수인지 확인한 뒤 다시 계산해주세요.</p>}
        {seed.input_source === "saved" && seed.profile_inputs && <button type="button" onClick={applyProfile} disabled={loading} className="mt-2 font-semibold text-primary underline disabled:opacity-50">공통 자금 조건 적용</button>}
      </div>}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* 왼쪽: 매수·대출 */}
        <div className="space-y-4">
          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="font-semibold mb-4 text-slate-700">매수 조건</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">매수가 *</label>
                <input aria-label="매수가 (원)" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 7억 5000만, 75000만"
                  value={purchasePriceStr} onChange={e => setPurchasePriceStr(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">매물 유형</label>
                <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={propType} onChange={e => setPropType(e.target.value)}>
                  {PROP_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label htmlFor="owned-homes" className="block text-xs text-slate-500 mb-1">취득 후 주택 수</label>
                <input id="owned-homes" aria-describedby="owned-homes-help" type="number" min={1} max={100} step={1} className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                  value={ownedHomes} onChange={e => setOwnedHomes(Number(e.target.value))} />
                <p id="owned-homes-help" className="mt-1 text-xs text-slate-500">이번 취득을 포함합니다. 첫 주택 취득은 1, 기존 1주택을 유지하며 추가 취득하면 2입니다.</p>
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="font-semibold mb-4 text-slate-700">대출 조건</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">대출 비율: {loanRatio}%</label>
                <input aria-label="대출 비율 (%)" type="range" min={0} max={90} step="any" value={loanRatio} onChange={e => setLoanRatio(Number(e.target.value))} className="w-full" />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">연 이율: {interestRate}%</label>
                <input aria-label="연 이율 (%)" type="range" min={0} max={30} step="any" value={interestRate}
                  onChange={e => setInterestRate(parseFloat(Number(e.target.value).toFixed(2)))} className="w-full" />
                {rateSource && <p className="text-[10px] text-primary mt-0.5">{rateSource} 자동 반영</p>}
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">연소득 (선택 — DSR 검증)</label>
                <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 8000만"
                  value={annualIncomeStr} onChange={e => setAnnualIncomeStr(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">대출 기간: {loanYears}년</label>
                <input aria-label="대출 기간 (년)" type="range" min={1} max={50} step={1} value={loanYears} onChange={e => setLoanYears(Number(e.target.value))} className="w-full" />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">상환 방식</label>
                <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={repayType} onChange={e => setRepayType(e.target.value)}>
                  {REPAY_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </div>
            </div>
          </div>
        </div>

        {/* 오른쪽: 보유·임대 */}
        <div className="space-y-4">
          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="font-semibold mb-4 text-slate-700">보유 계획</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">보유 기간: {holdingYears}년</label>
                <input type="range" min={1} max={20} value={holdingYears} onChange={e => setHoldingYears(Number(e.target.value))} className="w-full" />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">예상 연 상승률: {growthRate >= 0 ? "+" : ""}{growthRate}%</label>
                <input type="range" min={-10} max={20} step={0.5} value={growthRate}
                  onChange={e => setGrowthRate(parseFloat(Number(e.target.value).toFixed(1)))} className="w-full" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="font-semibold mb-4 text-slate-700">임대 수입</h2>
            <div className="space-y-3">
              <div className="flex gap-2">
                {RENTAL_MODES.map(m => (
                  <button key={m} onClick={() => setRentalMode(m)}
                    className={`flex-1 py-1.5 text-sm rounded-lg border ${rentalMode === m ? "bg-primary text-white border-primary" : "border-slate-300 text-slate-600 hover:bg-slate-50"}`}>
                    {m}
                  </button>
                ))}
              </div>
              {rentalMode === "전세" && (
                <div>
                  <label className="block text-xs text-slate-500 mb-1">전세 보증금</label>
                  <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 3억"
                    value={depositStr} onChange={e => setDepositStr(e.target.value)} />
                </div>
              )}
              {rentalMode === "임차인 승계" && (
                <div>
                  <label className="block text-xs text-slate-500 mb-1">승계할 임차 보증금</label>
                  <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 4억"
                    value={assumedStr} onChange={e => setAssumedStr(e.target.value)} />
                  <p className="mt-1 text-xs text-slate-500">잔금에서 이 금액을 뺀 대신, 임대차 종료 때 임차인에게 돌려줄 의무를 넘겨받습니다. 임차인이 있는 주택의 대출 가능 여부·한도 규정은 계산에 반영하지 않았으니 금융기관에 확인하세요.</p>
                </div>
              )}
              {rentalMode === "월세" && (
                <div>
                  <label className="block text-xs text-slate-500 mb-1">월세 (원)</label>
                  <input type="number" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 1500000"
                    value={rentFeeStr} onChange={e => setRentFeeStr(e.target.value)} />
                </div>
              )}
              {rentalMode === "월세" && (
                <div>
                  <label className="block text-xs text-slate-500 mb-1">공실률: {vacancyRate}%</label>
                  <input type="range" min={0} max={30} value={vacancyRate}
                    onChange={e => setVacancyRate(Number(e.target.value))} className="w-full" />
                </div>
              )}
              <div>
                <label className="block text-xs text-slate-500 mb-1">월 관리비 (원)</label>
                <input type="number" className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 200000"
                  value={mgmtFeeStr} onChange={e => setMgmtFeeStr(e.target.value)} />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow p-5">
            <h2 className="font-semibold mb-4 text-slate-700">세금 산정 (선택)</h2>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-slate-500 mb-1">공시가격 (보유세 산정 — 미입력 시 시세로 추정)</label>
                <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 5억"
                  value={officialPriceStr} onChange={e => setOfficialPriceStr(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 text-sm text-slate-600">
                <input type="checkbox" checked={adjustedArea} onChange={e => setAdjustedArea(e.target.checked)} />
                조정대상지역 (LTV 강화 적용)
              </label>
            </div>
          </div>

          <div className="bg-white rounded-xl shadow p-5 space-y-3">
            <h2 className="font-semibold">자금 판단 기준 (선택)</h2>
            {[
              { label: "보유 현금 (원)", value: cashStr, set: setCashStr },
              { label: "월 대출 상환 한도 (원)", value: paymentLimitStr, set: setPaymentLimitStr },
              { label: "기존 대출 연간 상환액 (원)", value: existingPaymentStr, set: setExistingPaymentStr },
            ].map(field => <label key={field.label} className="block text-xs text-slate-500">
              {field.label}<input aria-label={field.label} value={field.value} onChange={e => field.set(e.target.value)}
                className="mt-1 w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 1000000" />
            </label>)}
            <p className="text-xs text-slate-500">보유 현금은 취득비용을 포함해 비교합니다. 월 한도는 첫 달 대출 상환액 기준이며 생활비·관리비는 별도입니다.</p>
          </div>
          {error && <p className="text-red-500 text-sm">⚠️ {error}</p>}
          <button onClick={handleSubmit} disabled={loading}
            className="w-full py-3 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-primary-strong disabled:opacity-50">
            {loading ? "계산 중..." : "💰 시뮬레이션 계산"}
          </button>
        </div>
      </div>

      {/* 결과 */}
      {result && (
        <div className="mt-6">
          {seed.case_id && <p className="mb-4 rounded-xl bg-blue-50 p-4 text-sm">계산 결과를 후보에 저장했습니다. 입력을 바꾸면 다시 계산해야 반영됩니다. <Link className="underline" href={`/cases/${seed.case_id}/comparison`}>후보 비교·다음 행동 확인</Link></p>}
          <p className="mb-4 text-xs text-slate-500">입력 조건과 계산기 기준에 따른 참고 결과이며 금융기관의 대출 승인을 의미하지 않습니다.</p>
          <div className="flex border-b border-slate-200 mb-4 gap-1">
            {["📊 대시보드", "📄 리포트"].map((t, i) => (
              <button key={i} onClick={() => setTab(i)}
                className={`px-4 py-2 text-sm font-medium ${tab === i ? "tab-active" : "text-slate-500 hover:text-slate-700"}`}>{t}</button>
            ))}
          </div>

          {tab === 0 && (
            <div className="space-y-4">
              {/* LTV·DSR 규제 검증 배너 */}
              {result.finance_check && result.loan_amount > 0 && (
                <div className={`rounded-xl p-4 text-sm border ${
                  result.finance_check.ltv_exceeded || result.finance_check.dsr_exceeded
                    ? "bg-red-50 border-red-300 text-red-800"
                    : "bg-emerald-50 border-emerald-200 text-emerald-800"
                }`}>
                  <div className="font-semibold mb-1">
                    {result.finance_check.ltv_exceeded || result.finance_check.dsr_exceeded
                      ? "⛔ 대출 규제 한도 초과 — 이 조건의 대출은 실행이 어렵습니다"
                      : result.finance_check.dsr == null ? "연소득 미입력 — DSR 확인 필요" : "입력 조건이 계산기 기준 범위 이내입니다"}
                  </div>
                  <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs">
                    <span>
                      LTV {(result.finance_check.ltv * 100).toFixed(1)}% / 한도 {(result.finance_check.ltv_limit * 100).toFixed(0)}%
                      {result.finance_check.ltv_exceeded && ` (최대 ${fmt(result.finance_check.ltv_max_loan)})`}
                    </span>
                    {result.finance_check.dsr != null && (
                      <span>
                        DSR {(result.finance_check.dsr * 100).toFixed(1)}% / 한도 40%
                        (스트레스 금리 {result.finance_check.stress_rate}%)
                        {result.finance_check.dsr_exceeded && ` — 최대 ${fmt(result.finance_check.dsr_max_loan)}`}
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* 핵심 지표 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                {[
                  { label: "매수가", value: fmt(result.purchase_price) },
                  { label: "대출금", value: fmt(result.loan_amount) },
                  { label: "필요 현금", value: fmt(result.required_cash) },
                  { label: "실투자금", value: fmt(result.equity) },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-white rounded-xl shadow p-4">
                    <div className="text-xs text-slate-400">{label}</div>
                    <div className="font-bold mt-1 text-primary-strong">{value}</div>
                  </div>
                ))}
              </div>

              {/* 취득 비용 + 대출 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-white rounded-xl shadow p-5">
                  <h3 className="font-semibold mb-3">취득 비용</h3>
                  <table className="w-full text-sm">
                    <tbody>
                      {[
                        ["취득세", fmt(result.acquisition_cost.acquisition_tax)],
                        ["중개보수", fmt(result.acquisition_cost.brokerage_fee)],
                        ["기타", fmt(result.acquisition_cost.other_cost)],
                        ["합계", fmt(result.acquisition_cost.total)],
                      ].map(([k, v]) => (
                        <tr key={k} className="border-b border-slate-100 last:font-semibold">
                          <td className="py-1.5 text-slate-500">{k}</td>
                          <td className="py-1.5 text-right">{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {result.loan_amount > 0 && (
                  <div className="bg-white rounded-xl shadow p-5">
                    <h3 className="font-semibold mb-3">대출 정보</h3>
                    <table className="w-full text-sm">
                      <tbody>
                        {[
                          ["월 상환액", fmt(result.loan.monthly_payment)],
                          ["총 상환액", fmt(result.loan.total_repayment)],
                          ["총 이자", fmt(result.loan.total_interest)],
                        ].map(([k, v]) => (
                          <tr key={k} className="border-b border-slate-100 last:font-semibold">
                            <td className="py-1.5 text-slate-500">{k}</td>
                            <td className="py-1.5 text-right">{v}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              {/* 시나리오 */}
              <div className="bg-white rounded-xl shadow overflow-hidden">
                <h3 className="font-semibold p-4 pb-0">시나리오 비교</h3>
                <table className="w-full text-sm mt-3">
                  <thead className="bg-slate-50">
                    <tr>
                      {["지표", "비관", "기본", "낙관"].map(h => (
                        <th key={h} className="px-4 py-3 text-left font-semibold text-slate-600">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {(
                      [
                        ["연 상승률",      (s: ScenarioResult) => `${s.annual_growth_rate.toFixed(1)}%`],
                        ["예상 매도가",    (s: ScenarioResult) => fmt(s.expected_sale_price)],
                        ["시세 차익",      (s: ScenarioResult) => `${signLabel(s.capital_gain)} ${fmt(Math.abs(s.capital_gain))}`],
                        ["세전 순손익",    (s: ScenarioResult) => `${signLabel(s.pre_tax_profit)} ${fmt(Math.abs(s.pre_tax_profit))}`],
                        ["양도소득세",     (s: ScenarioResult) => s.capital_gains_tax ? `−${fmt(s.capital_gains_tax)}` : "0원 (비과세)"],
                        ["보유세 합계",    (s: ScenarioResult) => `−${fmt(s.holding_tax_total)}`],
                        ["매도 중개보수",  (s: ScenarioResult) => `−${fmt(s.sale_brokerage_fee)}`],
                        ["세후 순손익",    (s: ScenarioResult) => `${signLabel(s.net_profit)} ${fmt(Math.abs(s.net_profit))}`],
                        ["자기자본 수익률",(s: ScenarioResult) => s.infinite_leverage ? "무한 레버리지" : fmtPct(s.equity_roi)],
                        ["연환산 수익률",  (s: ScenarioResult) => s.infinite_leverage ? "—" : fmtPct(s.annual_equity_roi)],
                      ] as [string, (s: ScenarioResult) => string][]
                    ).map(([label, getter]) => (
                      <tr key={label}>
                        <td className="px-4 py-2.5 text-slate-500">{label}</td>
                        <td className="px-4 py-2.5 text-red-600">{getter(result.scenario_bear)}</td>
                        <td className="px-4 py-2.5 font-medium">{getter(result.scenario_base)}</td>
                        <td className="px-4 py-2.5 text-green-600">{getter(result.scenario_bull)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* 세금 근거 + 손익분기 */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-white rounded-xl shadow p-5 text-sm">
                  <h3 className="font-semibold mb-2">세금 산정 근거</h3>
                  <p className="text-xs text-slate-500 mb-1">{result.scenario_base.cgt_note}</p>
                  <p className="text-xs text-slate-400">
                    보유세 공시가격: {fmt(result.official_price_used)}
                    {result.official_price_estimated && " (시세×현실화율 추정)"}
                  </p>
                  <p className="text-xs text-slate-400 mt-1">세법 기준일: {result.tax_rules_as_of} · 간이 계산</p>
                </div>
                {result.breakeven_growth_rate != null && (
                  <div className="bg-white rounded-xl shadow p-5 text-sm">
                    <h3 className="font-semibold mb-2">손익분기 상승률</h3>
                    <p className="text-2xl font-bold text-primary-strong">연 {result.breakeven_growth_rate}%</p>
                    <p className="text-xs text-slate-400 mt-1">
                      모든 비용·세금 회수에 필요한 최소 연 상승률
                    </p>
                  </div>
                )}
              </div>

              {/* 금리 × 상승률 민감도 */}
              {result.rate_sensitivity.length > 0 && (() => {
                const rates   = [...new Set(result.rate_sensitivity.map(c => c.interest_rate))].sort((a, b) => a - b);
                const growths = [...new Set(result.rate_sensitivity.map(c => c.growth_rate))].sort((a, b) => a - b);
                const cell = (g: number, r: number) =>
                  result.rate_sensitivity.find(c => c.growth_rate === g && c.interest_rate === r);
                const roiColor = (v: number) =>
                  v >= 10 ? "bg-green-100 text-green-800" :
                  v >= 5  ? "bg-green-50 text-green-700" :
                  v >= 0  ? "bg-yellow-50 text-yellow-700" : "bg-red-50 text-red-600";
                return (
                  <div className="bg-white rounded-xl shadow overflow-hidden">
                    <h3 className="font-semibold p-4 pb-2">금리 × 상승률 민감도 <span className="text-xs font-normal text-slate-400">(세후 연환산 수익률)</span></h3>
                    <table className="w-full text-sm mb-2">
                      <thead>
                        <tr>
                          <th className="px-4 py-2 text-left text-xs text-slate-500">상승률 \ 금리</th>
                          {rates.map(r => <th key={r} className="px-4 py-2 text-center text-xs text-slate-500">{r}%</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {growths.map(g => (
                          <tr key={g}>
                            <td className="px-4 py-2 text-xs text-slate-500">연 {g >= 0 ? "+" : ""}{g.toFixed(1)}%</td>
                            {rates.map(r => {
                              const c = cell(g, r);
                              return (
                                <td key={r} className="px-2 py-1.5 text-center">
                                  {c ? (
                                    <span className={`inline-block w-full rounded px-2 py-1 text-xs font-medium ${roiColor(c.annual_equity_roi)}`}>
                                      {fmtPct(c.annual_equity_roi)}
                                    </span>
                                  ) : "—"}
                                </td>
                              );
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                );
              })()}

              {/* 투자 판단 */}
              {result.scenario_base.infinite_leverage ? (
                <div className="rounded-xl p-4 font-semibold text-center bg-purple-100 text-purple-700">
                  ♾️ 무한 레버리지 (실투자금 ≤ 0) — 수익률 정의 불가 · 역전세 시 보증금 반환 리스크 주의
                </div>
              ) : (
                <div className={`rounded-xl p-4 font-semibold text-center ${verdictStyle(result.scenario_base.annual_equity_roi)}`}>
                  {result.scenario_base.annual_equity_roi >= 10 && "✅ 우수한 투자 수익률 (세후 연 10% 이상)"}
                  {result.scenario_base.annual_equity_roi >= 5 && result.scenario_base.annual_equity_roi < 10 && "🟡 양호한 투자 수익률 (세후 연 5~10%)"}
                  {result.scenario_base.annual_equity_roi >= 0 && result.scenario_base.annual_equity_roi < 5 && "🟠 낮은 수익률 (세후 연 0~5%)"}
                  {result.scenario_base.annual_equity_roi < 0 && "🔴 마이너스 수익률 — 투자 재검토 필요"}
                </div>
              )}
            </div>
          )}

          {tab === 1 && (
            <div className="bg-white rounded-xl shadow p-6 prose text-sm text-slate-700 whitespace-pre-wrap">{report}</div>
          )}
        </div>
      )}
    </div>
  );
}
