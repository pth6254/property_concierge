"use client";
import ExternalListingLink from "@/components/ExternalListingLink";
import VerifiedListingLinks from "@/components/VerifiedListingLinks";
import DecisionJourney from "@/components/DecisionJourney";
import ConciergeComplexCard, { type ComplexCandidateInput } from "@/components/ConciergeComplexCard";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Building2, Check, Database, MapPinned } from "lucide-react";
import { api } from "@/lib/api";
import type { PurchaseCase } from "@/lib/types";

type District = {
  region_name: string; region_code: string; lawd_code: string; deal_count: number; avg_price: number;
  sample_size: number; median_price: number; price_q1: number; price_q3: number;
  avg_per_sqm: number; median_per_sqm: number; asset_count: number; last_deal_ym: string;
  budget_fit_count: number; budget_fit_ratio: number; confidence: "high" | "medium" | "low";
};
type Region = {
  code: string; parent_code: string | null; name: string; full_name: string;
  level: "sido" | "sigungu" | "eup_myeon_dong" | "eupmyeondong" | "ri"; lawd_code: string | null;
};
type Complex = {
  complex_name: string; dong: string; avg_price: number; avg_per_sqm: number;
  avg_area_m2: number; deal_count: number; build_year: number; last_deal_ym: string;
  score: number; reasons: string[];
};

const PROPERTY_TYPES = [
  ["all", "전체"], ["apartment", "아파트"], ["row_house", "연립·다세대"],
  ["detached", "단독·다가구"], ["officetel", "오피스텔"],
  ["non_residential", "상업·업무"], ["industrial", "공장·창고"], ["land", "토지"],
] as const;

const formatPrice = (manwon: number) => manwon >= 10_000
  ? `${(manwon / 10_000).toFixed(manwon % 10_000 ? 1 : 0)}억원`
  : `${manwon.toLocaleString()}만원`;
const formatYm = (ym: string) => ym?.length === 6 ? `${ym.slice(0, 4)}.${ym.slice(4)}` : ym;
const shortRegionName = (fullName: string) => fullName.split(" ").slice(1).join(" ") || fullName;
const CONFIDENCE = { high: "높음", medium: "보통", low: "낮음" } as const;

export default function ExploreWorkspace({ initialCaseId = "" }: { initialCaseId?: string }) {
  const [regions, setRegions] = useState<Region[]>([]);
  const [regionCode, setRegionCode] = useState("1100000000");
  const [districtOptions, setDistrictOptions] = useState<Region[]>([]);
  const [districtCode, setDistrictCode] = useState("");
  const [dongOptions, setDongOptions] = useState<Region[]>([]);
  const [dongCode, setDongCode] = useState("");
  const marketRequest = useRef(0);
  const complexRequest = useRef(0);
  const [propertyType, setPropertyType] = useState("apartment");
  const [budget, setBudget] = useState("");
  const [districts, setDistricts] = useState<District[]>([]);
  const [period, setPeriod] = useState<{ from: string; to: string } | null>(null);
  const [selected, setSelected] = useState<District | null>(null);
  const [complexes, setComplexes] = useState<Complex[]>([]);
  const [cases, setCases] = useState<PurchaseCase[]>([]);
  const [caseId, setCaseId] = useState(initialCaseId);
  const [saved, setSaved] = useState<Set<string>>(new Set());
  const [savedRegions, setSavedRegions] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [complexLoading, setComplexLoading] = useState(false);
  const [error, setError] = useState("");
  const saveLock = useRef(false);
  const [saving, setSaving] = useState(false);

  const loadDistricts = async (type = propertyType, maxBudget = budget, scopeCode = dongCode || districtCode || regionCode, byDong = Boolean(districtCode)) => {
    const request = ++marketRequest.current;
    ++complexRequest.current;
    setLoading(true); setError(""); setSelected(null); setComplexes([]); setDistricts([]);
    try {
      const result = await api.regionMarket({
        region_code: scopeCode, group_level: byDong ? "eup_myeon_dong" : "sigungu", months: 12, property_type: type,
        budget_max: maxBudget ? Math.round(Number(maxBudget) * 10_000) : undefined,
      });
      if (request !== marketRequest.current) return;
      setDistricts(result.items); setPeriod(result.period);
      if (scopeCode.slice(5, 8) !== "000" && result.items[0]) {
        void chooseDistrict(result.items[0], type, maxBudget);
      }
    } catch { if (request === marketRequest.current) setError("수집된 실거래 데이터를 불러오지 못했습니다."); }
    finally { if (request === marketRequest.current) setLoading(false); }
  };

  useEffect(() => {
    let cancelled = false;
    const request = ++marketRequest.current;
    Promise.all([
      api.marketRegions(),
      api.cases(),
    ])
      .then(([regionResult, caseResult]) => {
        if (cancelled) return;
        setRegions(regionResult.items); setCases(caseResult.items);
        if (initialCaseId && !caseResult.items.some(item => String(item.id) === initialCaseId)) {
          setCaseId("");setError("연결할 케이스를 찾을 수 없습니다. 검토할 케이스를 다시 선택해주세요.");
        }
      })
      .catch(() => { if (!cancelled) setError("탐색 데이터를 불러오지 못했습니다."); });
    api.regionMarket({ region_code: "1100000000", months: 12, property_type: "apartment" })
      .then((market) => {
        if (!cancelled && request === marketRequest.current) {
          setDistricts(market.items); setPeriod(market.period);
        }
      })
      .catch(() => { if (!cancelled && request === marketRequest.current) setError("실거래 집계를 불러오지 못했습니다."); })
      .finally(() => { if (!cancelled && request === marketRequest.current) setLoading(false); });
    return () => { cancelled = true; };
  }, [initialCaseId]);

  useEffect(() => {
    let cancelled = false;
    api.marketRegions({ level: "sigungu", parent_code: regionCode })
      .then((result) => { if (!cancelled) setDistrictOptions(result.items); })
      .catch(() => { if (!cancelled) setError("시·군·구 목록을 불러오지 못했습니다."); });
    return () => { cancelled = true; };
  }, [regionCode]);

  useEffect(() => {
    if (!districtCode) return;
    let cancelled = false;
    api.marketRegions({ level: "eup_myeon_dong", parent_code: districtCode })
      .then((result) => { if (!cancelled) setDongOptions(result.items); })
      .catch(() => { if (!cancelled) setError("읍·면·동 목록을 불러오지 못했습니다."); });
    return () => { cancelled = true; };
  }, [districtCode]);

  const selectedRegion = regions.find((region) => region.code === regionCode);
  const selectedDistrict = districtOptions.find((region) => region.code === districtCode);
  const selectedDong = dongOptions.find((region) => region.code === dongCode);

  const changeRegion = (nextCode: string) => {
    setRegionCode(nextCode); setDistrictCode(""); setDistrictOptions([]);
    setDongCode(""); setDongOptions([]);
    loadDistricts(propertyType, budget, nextCode, false);
  };

  const changeDistrict = (code: string) => {
    setDistrictCode(code); setDongCode(""); setDongOptions([]);
    void loadDistricts(propertyType, budget, code || regionCode, Boolean(code));
  };

  const changeDong = (code: string) => {
    setDongCode(code);
    void loadDistricts(propertyType, budget, code || districtCode, true);
  };

  const ranked = useMemo(() => [...districts].sort((a, b) => {
    if (budget) {
      const aRatio = a.deal_count ? a.budget_fit_count / a.deal_count : 0;
      const bRatio = b.deal_count ? b.budget_fit_count / b.deal_count : 0;
      if (aRatio !== bRatio) return bRatio - aRatio;
    }
    return b.deal_count - a.deal_count;
  }), [districts, budget]);

  const chooseDistrict = async (district: District, type = propertyType, maxBudget = budget) => {
    const request = ++complexRequest.current;
    setSelected(district); setComplexLoading(true); setComplexes([]); setError("");
    if (type !== "apartment") {
      setComplexLoading(false);
      return;
    }
    try {
      const result = caseId ? await api.caseRecommendations(Number(caseId), district.region_code) : await api.recommendComplexes({
        region: district.region_name, region_code: district.region_code, months: 12, limit: 10,
        budget_max: maxBudget ? Number(maxBudget) * 10_000 : 0,
      });
      if (request !== complexRequest.current) return;
      if (result.error) throw new Error(result.error);
      setComplexes(result.results);
    } catch (reason) {
      if (request !== complexRequest.current) return;
      setError(reason instanceof Error ? reason.message : "단지 데이터를 불러오지 못했습니다.");
    } finally { if (request === complexRequest.current) setComplexLoading(false); }
  };

  const ensureCaseAndRegion = async (district: District) => {
    let targetCaseId = caseId;
    if (!targetCaseId) {
      const created = await api.createCase({
        title: `${shortRegionName(district.region_name)} 매수 검토`,
        budget_max: budget ? Number(budget) * 100_000_000 : undefined,
      });
      targetCaseId = String(created.id);
      setCases(current => [created, ...current]);
      setCaseId(targetCaseId);
    }
    await api.addCaseRegion(Number(targetCaseId), {
      region_code: district.region_code,
      property_type: propertyType,
      budget_max_won: budget ? Number(budget) * 100_000_000 : undefined,
      months: 12,
      source: "market_explorer",
    });
    setSavedRegions((current) => new Set(current).add(`${targetCaseId}:${district.region_code}`));
    return targetCaseId;
  };

  const saveRegion = async () => {
    if (!selected || saveLock.current) return;
    saveLock.current = true; setSaving(true);
    setError("");
    try { await ensureCaseAndRegion(selected); }
    catch { setError("관심 지역을 검토 케이스에 저장하지 못했습니다."); }
    finally { saveLock.current = false; setSaving(false); }
  };

  const saveComplex = async (complex: Complex, input: ComplexCandidateInput) => {
    if (!selected || saveLock.current) throw new Error("진행 중인 저장이 끝난 뒤 다시 시도해주세요.");
    saveLock.current = true; setSaving(true);
    try {
    const targetCaseId = await ensureCaseAndRegion(selected);
    await api.addCaseProperty(Number(targetCaseId), {
      name: complex.complex_name,
      address: input.address,
      category: "아파트",
      area_sqm: input.area_sqm,
      asking_price: input.asking_price,
      source: "recommendation",
      notes: `국토부 실거래 ${complex.deal_count}건 기준 평균 ${formatPrice(complex.avg_price)} · 기준월 ${formatYm(complex.last_deal_ym)}`,
    });
    setSaved((current) => new Set(current).add(`${targetCaseId}:${complex.dong}:${complex.complex_name}`));
    } finally { saveLock.current = false; setSaving(false); }
  };

  return (
    <div className="mx-auto max-w-7xl">
      <div className="mb-6">
        <DecisionJourney current="explore" caseId={caseId} />
        <h1 className="text-2xl font-bold text-slate-900">동네 탐색</h1>
        <p className="mt-1 text-sm text-slate-500">서울특별시 → 구 → 동 순서로 범위를 좁혀 매매 실거래를 비교·분석하세요. 동은 법정동 기준입니다.</p>
      </div>

      <section className="mb-5 rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 md:items-end">
          <div><label htmlFor="explore-sido" className="mb-2 block text-xs font-semibold text-slate-600">시·도</label><select id="explore-sido" value={regionCode} onChange={(e) => changeRegion(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/30">{regions.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}</select></div>
          <div><label htmlFor="explore-district" className="mb-2 block text-xs font-semibold text-slate-600">시·군·구</label><select id="explore-district" value={districtCode} onChange={(e) => changeDistrict(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"><option value="">전체 구 비교</option>{districtOptions.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}</select></div>
          <div><label htmlFor="explore-dong" className="mb-2 block text-xs font-semibold text-slate-600">읍·면·동 (법정동)</label><select id="explore-dong" value={dongCode} disabled={!districtCode} onChange={(e) => changeDong(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm disabled:bg-slate-100 disabled:text-slate-400"><option value="">{districtCode ? "전체 동 비교" : "구를 먼저 선택하세요"}</option>{dongOptions.map((region) => <option key={region.code} value={region.code}>{region.name}</option>)}</select></div>
          <div><label className="mb-2 block text-xs font-semibold text-slate-600">부동산 유형</label><div className="flex flex-wrap gap-2">{PROPERTY_TYPES.map(([value, label]) => <button key={value} onClick={() => { setPropertyType(value); loadDistricts(value, budget); }} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${propertyType === value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>{label}</button>)}</div></div>
          <div><label className="mb-2 block text-xs font-semibold text-slate-600">최대 예산</label><div className="flex items-center rounded-lg border border-slate-300 px-3"><input type="number" min="0" value={budget} onChange={(e) => setBudget(e.target.value)} onKeyDown={(e) => e.key === "Enter" && loadDistricts()} placeholder="예: 12" className="min-w-0 flex-1 py-2 text-sm outline-none" /><span className="text-xs text-slate-400">억원</span></div></div>
          <button onClick={() => loadDistricts()} className="rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-white hover:bg-primary-strong">조건 적용</button>
        </div>
        <nav aria-label="선택한 지역 경로" className="mt-4 flex flex-wrap items-center gap-2 text-sm">
          <button onClick={() => changeDistrict("")} className="font-semibold text-primary hover:underline">{selectedRegion?.name ?? "서울특별시"}</button>
          <ArrowRight size={14} className="text-slate-300" />
          {districtCode ? <button onClick={() => changeDong("")} className="font-semibold text-primary hover:underline">{selectedDistrict?.name ?? "선택한 구"}</button> : <span className="text-slate-500">전체 구 비교</span>}
          {districtCode && <><ArrowRight size={14} className="text-slate-300" /><span aria-current="location" className="text-slate-600">{selectedDong?.name ?? "전체 동 비교"}</span></>}
        </nav>
        {period && <div className="mt-4 flex items-center gap-2 border-t border-slate-100 pt-3 text-xs text-slate-500"><Database size={14} className="text-primary" /><strong>국토교통부 실거래가</strong><span>{formatYm(period.from)}~{formatYm(period.to)}</span><span>· 해제 거래 제외</span><span>· 금액 단위 만원</span></div>}
      </section>
      {error && <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p>}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4 text-sm">
        <label className="min-w-0 font-semibold">검토할 케이스<select aria-label="검토할 케이스" value={caseId} disabled={saving} onChange={(e)=>setCaseId(e.target.value)} className="mt-2 block w-full max-w-full rounded-lg border border-slate-300 p-2 font-normal sm:ml-2 sm:mt-0 sm:inline-block sm:w-auto"><option value="">후보 저장 시 새 케이스 생성</option>{cases.map(item=><option key={item.id} value={item.id}>{item.title}</option>)}</select></label>
        {caseId && <Link href={`/cases/${caseId}`} className="font-semibold text-primary hover:underline">선택한 케이스로 이동 →</Link>}
      </div>
      {selected && <section aria-label="선택한 동의 실거래 지표" className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">거래 표본</p><strong className="mt-1 block text-lg">{selected.sample_size.toLocaleString()}건</strong><p className="text-xs text-slate-400">최근 거래 {formatYm(selected.last_deal_ym)}</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">거래가격 중앙값</p><strong className="mt-1 block text-lg">{formatPrice(selected.median_price)}</strong><p className="text-xs text-slate-400">평균 {formatPrice(selected.avg_price)}</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">㎡당 가격 중앙값</p><strong className="mt-1 block text-lg">{selected.median_per_sqm.toLocaleString()}만원/㎡</strong><p className="text-xs text-slate-400">면적당 신고 거래가격</p></div>
        <div className="rounded-xl border border-slate-200 bg-white p-4"><p className="text-xs text-slate-500">예산 내 거래</p><strong className="mt-1 block text-lg">{budget ? `${selected.budget_fit_count.toLocaleString()}건` : "예산 미설정"}</strong><p className="text-xs text-slate-400">{budget ? `전체 표본의 ${Math.round(selected.budget_fit_ratio * 100)}%` : "예산 입력 후 조건을 적용하세요"}</p></div>
      </section>}

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(380px,0.9fr)]">
        <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
          <div className="border-b border-slate-100 p-4"><h2 className="font-bold">{selectedDong?.name ?? selectedDistrict?.name ?? selectedRegion?.name ?? "선택 지역"} {dongCode ? "실거래 분석" : districtCode ? "법정 읍·면·동 비교" : "시·군·구 비교"}</h2><p className="text-xs text-slate-400">{dongCode ? "선택한 동의 거래 통계" : "거래량 순"}{budget && " · 예산 내 거래 비중 우선"}</p></div>
          {loading ? <div className="py-20 text-center text-slate-400">실거래 집계 중...</div> : <div className="max-h-[680px] divide-y divide-slate-100 overflow-y-auto">{ranked.length === 0 ? <p className="p-8 text-sm text-slate-500">선택한 지역·유형으로 수집된 실거래가 없습니다. 상위 지역이나 다른 유형을 선택해 주세요.</p> : ranked.map((district, index) => {
            const fit = Math.round(district.budget_fit_ratio * 100);
            return <button key={district.region_code} onClick={() => !districtCode ? changeDistrict(district.region_code) : changeDong(district.region_code)} className={`grid w-full grid-cols-[32px_1fr_auto] items-center gap-3 p-4 text-left hover:bg-emerald-50 ${selected?.region_code === district.region_code ? "bg-emerald-50 ring-1 ring-inset ring-emerald-200" : ""}`}><span className="text-xs font-bold text-slate-300">{index + 1}</span><span><strong className="block text-sm text-slate-800">{shortRegionName(district.region_name)}</strong><span className="block text-xs font-semibold text-primary">{!districtCode ? "동별 비교 보기 →" : "동 상세 분석 보기 →"}</span><span className="text-xs text-slate-400">표본 {district.sample_size.toLocaleString()}건 · 신뢰도 {CONFIDENCE[district.confidence]}</span>{budget && <span className="mt-1 block text-xs font-semibold text-emerald-600">예산 내 거래 {fit}%</span>}</span><span className="text-right"><strong className="block text-sm text-slate-800">{formatPrice(district.median_price)}</strong><span className="text-xs text-slate-400">중앙값 · {formatPrice(district.price_q1)}~{formatPrice(district.price_q3)}</span></span></button>;
          })}</div>}
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          {!selected ? <div className="flex min-h-[420px] flex-col items-center justify-center p-8 text-center"><MapPinned size={40} className="mb-3 text-slate-200" /><h2 className="font-bold text-slate-700">{districtCode ? "분석할 동을 선택하세요." : "구를 선택해 동별로 비교하세요."}</h2><p className="mt-1 text-sm text-slate-400">목록을 누르거나 상단 지역 선택으로 범위를 좁힐 수 있습니다. 아파트는 동별 단지 후보까지 이어서 볼 수 있습니다.</p></div> : <>
            <div className="border-b border-slate-100 p-4"><div className="flex items-start justify-between gap-3"><div><h2 className="font-bold">{shortRegionName(selected.region_name)} {propertyType === "apartment" ? "단지 후보" : "지역 거래 현황"}</h2><p className="text-xs text-slate-400">중앙 {formatPrice(selected.median_price)} · 범위 {formatPrice(selected.price_q1)}~{formatPrice(selected.price_q3)} · 신뢰도 {CONFIDENCE[selected.confidence]}</p></div><button onClick={saveRegion} disabled={saving || savedRegions.has(`${caseId}:${selected.region_code}`)} className="shrink-0 rounded-lg border border-emerald-200 px-3 py-1.5 text-xs font-semibold text-primary hover:bg-emerald-50 disabled:bg-emerald-50">{savedRegions.has(`${caseId}:${selected.region_code}`) ? <><Check size={13} className="mr-1 inline" />지역 저장됨</> : cases.length ? "관심 지역 저장" : "케이스 만들고 저장"}</button></div><p className="mt-2 text-xs text-slate-400">실거래를 바탕으로 찾은 단지입니다. 현재 판매 매물은 네이버에서 확인하거나 직접 등록하세요.</p></div>
            <div className="p-4"><ExternalListingLink query={selected.region_name} context={{ address: selected.region_name, propertyType, caseId }} /></div>
            <VerifiedListingLinks key={`${selected.region_code}:${propertyType}`} regionCode={selected.region_code} propertyType={propertyType} caseId={caseId} />
            {propertyType !== "apartment" ? <div className="px-8 py-12 text-sm text-slate-600">수집된 거래 {selected.sample_size.toLocaleString()}건 · 최근 거래 {formatYm(selected.last_deal_ym)}<br />중앙값 {formatPrice(selected.median_price)} · 평균 {formatPrice(selected.avg_price)}<p className="mt-3">이 유형은 단지 순위 대신 지역 거래를 비교합니다. 관심 지역을 케이스에 저장하고, 확인한 개별 물건을 후보로 등록해 자금·시세 분석을 이어가세요.</p><div className="mt-4 flex flex-wrap gap-3"><button onClick={saveRegion} disabled={saving} className="rounded border border-primary px-3 py-2 font-semibold text-primary">이 지역을 케이스에 저장</button><Link href={caseId?`/cases/${caseId}`:`/listings?property_type=${propertyType}`} className="rounded bg-primary px-3 py-2 font-semibold text-white">{caseId?"케이스에서 후보 등록":"매물 보관함에서 후보 등록"}</Link></div></div> : complexLoading ? <div className="py-12 text-center text-slate-500" role="status">단지 분석 중...</div> : complexes.length === 0 ? <p className="p-6 text-sm text-slate-500">현재 조건에 맞는 단지 후보가 없습니다. 예산이나 지역 범위를 조정해보세요.</p> : <div className="max-h-[760px] space-y-4 overflow-y-auto p-4">{complexes.map((complex, index) => {
              const isSaved = saved.has(`${caseId}:${complex.dong}:${complex.complex_name}`);
              return <div key={`${complex.dong}:${complex.complex_name}`}>
                <p className="mb-2 text-xs font-semibold text-slate-500">실거래 탐색 후보 {index + 1} · {formatYm(complex.last_deal_ym)} 기준</p>
                <ConciergeComplexCard item={complex} region={selected.region_name} caseId={caseId} disabled={saving || isSaved} saved={isSaved} saveLabel="케이스에 후보 저장" onSave={(input)=>saveComplex(complex,input)} />
              </div>;
            })}</div>}


          </>}
        </section>
      </div>

      <div className="mt-5 rounded-xl bg-amber-50 p-4 text-xs leading-5 text-amber-800"><Building2 size={15} className="mr-2 inline" /><strong>데이터 해석:</strong> 동별 비교는 행정동이 아닌 법정동 기준이며, 코드·이름으로 동을 확인할 수 없는 거래는 동 집계에서 제외됩니다. 평균가는 선택 기간의 신고 실거래를 단순 집계한 탐색 지표입니다. 개별 동·층·면적·상태에 따른 가격 차이가 있으므로 후보 저장 후 시세추정을 진행하세요.</div>
    </div>
  );
}
