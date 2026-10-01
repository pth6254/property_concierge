"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { parseWon } from "@/lib/moneyInput";
import { removeSessionValue, setSessionValue } from "@/lib/sessionStore";
import type { ComplexAddress, RecommendationResult } from "@/lib/types";
import ComplexAddressDetails from "@/components/ComplexAddressDetails";
import ExternalListingLink from "@/components/ExternalListingLink";

const REGIONS    = ["전체", "강남구", "마포구", "서초구", "송파구", "용산구", "성동구", "강동구", "영등포구"];
const PROP_TYPES = ["전체", "주거용", "상업용", "업무용", "산업용", "토지"];
const PURPOSES   = ["전체", "실거주", "투자", "매도", "보유"];

function parsePrice(s: string): number | undefined {
  if (!s.trim()) return undefined;
  return parseWon(s);
}

function ScoreBar({ score, max = 10 }: { score?: number; max?: number }) {
  const pct = ((score || 0) / max) * 100;
  const color = pct >= 70 ? "bg-green-500" : pct >= 40 ? "bg-yellow-500" : "bg-red-400";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 bg-slate-100 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-slate-500 w-6">{score?.toFixed(1) || "—"}</span>
    </div>
  );
}

type ComplexResult = ComplexAddress & {
  complex_name: string; dong: string; avg_price: number;
  avg_per_sqm: number; avg_area_m2: number; deal_count: number;
  build_year: number; last_deal_ym: string; score: number; reasons: string[];
};

function fmtEok(manwon: number): string {
  if (manwon >= 10000) {
    const eok = manwon / 10000;
    return eok >= 100 ? `${Math.round(eok)}억` : `${eok.toFixed(1)}억`;
  }
  return `${manwon.toLocaleString("ko-KR")}만원`;
}

export default function RecommendationPage() {
  const router = useRouter();

  // 추천 모드: 실거래 단지(전국) | 샘플 매물
  const [mode, setMode] = useState<"complex" | "listing">("complex");

  // 단지 추천 상태
  const [cxRegion, setCxRegion]       = useState("");
  const [cxBudgetMin, setCxBudgetMin] = useState("");
  const [cxBudgetMax, setCxBudgetMax] = useState("");
  const [cxArea, setCxArea]           = useState("");
  const [cxMonths, setCxMonths]       = useState(6);
  const [cxLimit, setCxLimit]         = useState(5);
  const [cxResults, setCxResults]     = useState<ComplexResult[]>([]);
  const [cxMeta, setCxMeta]           = useState<{ sample: number; complexes: number; avgPerSqm: number } | null>(null);
  const [cxLoading, setCxLoading]     = useState(false);
  const [cxError, setCxError]         = useState("");

  const handleComplexSubmit = async () => {
    if (!cxRegion.trim()) { setCxError("지역명을 입력하세요 (예: 춘천시, 해운대구)"); return; }
    if ([cxBudgetMin, cxBudgetMax].some(value => value.trim() && !Number.isSafeInteger(parseWon(value)))) {
      setCxError("예산은 250000000, 2.5억, 2억 5000만처럼 입력해주세요."); return;
    }
    setCxError("");
    setCxLoading(true);
    setCxResults([]);
    setCxMeta(null);
    try {
      const res = await api.recommendComplexes({
        region:     cxRegion.trim(),
        budget_min: cxBudgetMin ? Math.round((parsePrice(cxBudgetMin) || 0) / 10000) : 0,
        budget_max: cxBudgetMax ? Math.round((parsePrice(cxBudgetMax) || 0) / 10000) : 0,
        area_m2:    cxArea ? parseFloat(cxArea) : 0,
        months:     cxMonths,
        limit:      cxLimit,
      });
      if (res.error) throw new Error(res.error);
      setCxResults(res.results);
      setCxMeta({ sample: res.sample_count, complexes: res.complex_count, avgPerSqm: res.region_avg_per_sqm });
    } catch (e: unknown) {
      setCxError(e instanceof Error ? e.message : "단지 추천 실패");
    } finally {
      setCxLoading(false);
    }
  };

  const [region, setRegion]   = useState("전체");
  const [propType, setPropType] = useState("전체");
  const [purpose, setPurpose] = useState("전체");
  const [budgetMin, setBudgetMin] = useState("");
  const [budgetMax, setBudgetMax] = useState("");
  const [area, setArea]       = useState("");
  const [limit, setLimit]     = useState(5);
  const [results, setResults] = useState<RecommendationResult[]>([]);
  const [report, setReport]   = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [tab, setTab]         = useState(0);
  const [basket, setBasket]   = useState<RecommendationResult[]>([]);

  const handleSubmit = async () => {
    if ([budgetMin, budgetMax].some(value => value.trim() && !Number.isSafeInteger(parseWon(value)))) {
      setError("예산은 250000000, 2.5억, 2억 5000만처럼 입력해주세요."); return;
    }
    setError("");
    setLoading(true);
    setResults([]);
    try {
      const res = await api.recommendation({
        region:        region === "전체" ? undefined : region,
        property_type: propType === "전체" ? undefined : propType,
        purpose:       purpose === "전체" ? undefined : purpose,
        budget_min:    parsePrice(budgetMin),
        budget_max:    parsePrice(budgetMax),
        area_m2:       area ? parseFloat(area) : undefined,
        limit,
      }) as { results?: RecommendationResult[]; report?: string; error?: string };

      if (res.error) throw new Error(res.error);
      setResults(res.results || []);
      setReport(res.report || "");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "추천 실패");
    } finally {
      setLoading(false);
    }
  };

  const addToBasket = (r: RecommendationResult) => {
    if (basket.find(b => b.listing.listing_id === r.listing.listing_id)) return;
    if (basket.length >= 5) { alert("최대 5개까지 비교 가능합니다."); return; }
    const next = [...basket, r];
    setBasket(next);
    setSessionValue("comparisonBasket", JSON.stringify(next));
  };

  const simFromListing = (r: RecommendationResult) => {
    setSessionValue("simFromListing", JSON.stringify(r.listing));
    router.push("/simulation");
  };

  const goCompare = () => router.push("/comparison");

  const fmt = (n?: number) => n ? n.toLocaleString("ko-KR") + "원" : "—";

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-start gap-6">
        {/* 메인 */}
        <div className="flex-1">
          <h1 className="text-2xl font-bold mb-1">단지 추천·샘플</h1>
          <p className="text-slate-500 text-sm mb-4">실거래 단지 추천과 가상 매물 체험 도구입니다. 실제 매수 검토는 동네 탐색과 매수 검토 케이스에서 진행하세요.</p>
          <a href="/explore" className="mb-4 inline-block text-sm font-semibold text-primary underline">동네 탐색에서 매수 검토 시작 →</a>

          {/* 모드 토글 */}
          <div className="flex gap-1 mb-5 bg-slate-100 rounded-xl p-1 w-fit">
            {([
              { key: "complex", label: "🏢 실거래 단지 추천 (전국)" },
              { key: "listing", label: "📋 샘플 매물 추천" },
            ] as const).map(({ key, label }) => (
              <button key={key} onClick={() => setMode(key)}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  mode === key ? "bg-white shadow text-primary-strong" : "text-slate-500 hover:text-slate-700"
                }`}>
                {label}
              </button>
            ))}
          </div>

          {/* ══ 실거래 단지 추천 모드 ══ */}
          {mode === "complex" && (
            <>
              <div className="bg-white rounded-xl shadow p-5 mb-5">
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">지역 (전국 시군구)</label>
                    <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      placeholder="예: 춘천시, 해운대구, 서초구"
                      value={cxRegion} onChange={e => setCxRegion(e.target.value)}
                      onKeyDown={e => e.key === "Enter" && handleComplexSubmit()} />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">예산 최소</label>
                    <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      placeholder="예: 2억" value={cxBudgetMin} onChange={e => setCxBudgetMin(e.target.value)} />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">예산 최대</label>
                    <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      placeholder="예: 5억" value={cxBudgetMax} onChange={e => setCxBudgetMax(e.target.value)} />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">전용면적 (㎡, 선택)</label>
                    <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      placeholder="예: 84" value={cxArea} onChange={e => setCxArea(e.target.value)} />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">분석 기간</label>
                    <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      value={cxMonths} onChange={e => setCxMonths(Number(e.target.value))}>
                      <option value={3}>최근 3개월</option>
                      <option value={6}>최근 6개월</option>
                      <option value={12}>최근 12개월</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 mb-1">추천 수</label>
                    <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm"
                      value={cxLimit} onChange={e => setCxLimit(Number(e.target.value))}>
                      {[3, 5, 10].map(n => <option key={n} value={n}>{n}개</option>)}
                    </select>
                  </div>
                </div>
                <button onClick={handleComplexSubmit} disabled={cxLoading}
                  className="w-full py-2.5 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-primary-strong disabled:opacity-50">
                  {cxLoading ? "실거래 데이터 분석 중... (최초 조회 시 수십 초)" : "🔍 단지 추천받기"}
                </button>
                {cxError && <p className="text-red-500 text-sm mt-2">⚠️ {cxError}</p>}
              </div>

              {cxMeta && (
                <p className="text-xs text-slate-400 mb-3">
                  실거래 {cxMeta.sample.toLocaleString()}건 · 단지 {cxMeta.complexes}개 분석
                  · 지역 평균 평단가 {cxMeta.avgPerSqm.toLocaleString()}만원/㎡
                </p>
              )}

              {cxResults.length > 0 && (
                <div className="space-y-4">
                  {cxResults.map((c, i) => (
                    <div key={`${c.dong}:${c.complex_name}`} className="bg-white rounded-xl shadow p-5 border-l-4 border-emerald-500">
                      <div className="flex justify-between items-start mb-2">
                        <div>
                          <span className="text-xs text-emerald-700 font-bold bg-emerald-50 px-2 py-0.5 rounded-full">{i + 1}위</span>
                          <h3 className="font-bold mt-1">{c.complex_name}</h3>
                          <p className="text-xs text-slate-400">{c.dong} · 평균 전용 {c.avg_area_m2}㎡{c.build_year ? ` · ${c.build_year}년 준공` : ""}</p>
                        </div>
                        <div className="text-right">
                          <div className="font-bold text-emerald-700">{fmtEok(c.avg_price)}</div>
                          <div className="text-xs text-slate-400">{c.avg_per_sqm.toLocaleString()}만원/㎡ · {c.deal_count}건</div>
                        </div>
                      </div>
                      <ComplexAddressDetails item={c} />
                      <ExternalListingLink context={{ name: c.complex_name, address: c.road_address || c.jibun_address || `${cxRegion} ${c.dong}`, propertyType: "apartment" }} compact />
                      <div className="flex items-center gap-2 mb-2">
                        <span className="text-xs text-slate-500 w-14">종합 점수</span>
                        <ScoreBar score={c.score} />
                      </div>
                      {c.reasons.length > 0 && (
                        <div>
                          {c.reasons.map((rn, j) => (
                            <span key={j} className="inline-block text-xs bg-emerald-50 text-emerald-700 px-2 py-0.5 rounded mr-1 mb-1">✅ {rn}</span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  <p className="text-xs text-slate-400">
                    ⚠️ 국토부 실거래가 기반 추정 시세입니다. 실제 매물 존재 여부·호가는 별도 확인이 필요합니다.
                  </p>
                </div>
              )}
            </>
          )}

          {/* ══ 샘플 매물 추천 모드 ══ */}
          {mode === "listing" && (<>
          <p className="text-xs text-amber-600 bg-amber-50 rounded-lg px-3 py-2 mb-4">
            ⚠️ 샘플 매물 모드는 개발·테스트용 가상 매물(서울 8개 구, 43건) 기반입니다.
          </p>

          {/* 검색 폼 */}
          <div className="bg-white rounded-xl shadow p-5 mb-5">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-4">
              <div>
                <label className="block text-xs text-slate-500 mb-1">지역</label>
                <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={region} onChange={e => setRegion(e.target.value)}>
                  {REGIONS.map(r => <option key={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">매물 유형</label>
                <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={propType} onChange={e => setPropType(e.target.value)}>
                  {PROP_TYPES.map(t => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">투자 목적</label>
                <select className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" value={purpose} onChange={e => setPurpose(e.target.value)}>
                  {PURPOSES.map(p => <option key={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">예산 최소 (예: 5억)</label>
                <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 3억" value={budgetMin} onChange={e => setBudgetMin(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">예산 최대 (예: 10억)</label>
                <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 10억" value={budgetMax} onChange={e => setBudgetMax(e.target.value)} />
              </div>
              <div>
                <label className="block text-xs text-slate-500 mb-1">면적 (㎡)</label>
                <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 84" value={area} onChange={e => setArea(e.target.value)} />
              </div>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <label className="text-xs text-slate-500">추천 수</label>
                <input type="range" min={1} max={10} value={limit} onChange={e => setLimit(Number(e.target.value))} className="w-24" />
                <span className="text-sm font-medium text-primary-strong">{limit}개</span>
              </div>
              <button onClick={handleSubmit} disabled={loading}
                className="flex-1 py-2.5 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-primary-strong disabled:opacity-50">
                {loading ? "추천 분석 중..." : "🔍 매물 추천받기"}
              </button>
            </div>
            {error && <p className="text-red-500 text-sm mt-2">⚠️ {error}</p>}
          </div>

          {/* 결과 탭 */}
          {results.length > 0 && (
            <>
              <div className="flex border-b border-slate-200 mb-4 gap-1">
                {["🏠 추천 카드", "📄 리포트"].map((t, i) => (
                  <button key={i} onClick={() => setTab(i)}
                    className={`px-4 py-2 text-sm font-medium ${tab === i ? "tab-active" : "text-slate-500 hover:text-slate-700"}`}>
                    {t}
                  </button>
                ))}
              </div>

              {tab === 0 && (
                <div className="space-y-4">
                  {results.map((r, i) => (
                    <div key={r.listing.listing_id} className="bg-white rounded-xl shadow p-5 border-l-4 border-primary">
                      <div className="flex justify-between items-start mb-3">
                        <div>
                          <span className="text-xs text-primary font-bold bg-emerald-50 px-2 py-0.5 rounded-full">{i + 1}위</span>
                          <span className={`ml-2 text-xs px-2 py-0.5 rounded-full font-medium ${
                            r.total_score >= 7 ? "bg-green-100 text-green-700" :
                            r.total_score >= 5 ? "bg-yellow-100 text-yellow-700" : "bg-red-100 text-red-700"
                          }`}>{r.recommendation_label || "—"}</span>
                          <h3 className="font-bold mt-1">{r.listing.complex_name || r.listing.address}</h3>
                          <p className="text-xs text-slate-400">{r.listing.address}</p>
                        </div>
                        <div className="text-right">
                          <div className="font-bold text-primary-strong">{fmt(r.listing.asking_price)}</div>
                          {r.listing.area_m2 && <div className="text-xs text-slate-400">{r.listing.area_m2.toFixed(1)}㎡</div>}
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 mb-3 text-xs text-slate-500">
                        {r.listing.floor && <span>🏢 {r.listing.floor}층</span>}
                        {r.listing.built_year && <span>🏗️ {r.listing.built_year}년</span>}
                        {r.listing.station_distance_m && <span>🚇 {r.listing.station_distance_m}m</span>}
                        {r.listing.deposit_price && <span>💰 보증금 {fmt(r.listing.deposit_price)}</span>}
                      </div>

                      {/* 점수 바 */}
                      <div className="space-y-1.5 mb-3">
                        {[
                          { label: "가격", score: r.price_score },
                          { label: "입지", score: r.location_score },
                          { label: "투자", score: r.investment_score },
                          { label: "리스크", score: r.risk_score },
                        ].map(({ label, score }) => (
                          <div key={label} className="flex items-center gap-2 text-xs">
                            <span className="w-10 text-slate-500">{label}</span>
                            <ScoreBar score={score} />
                          </div>
                        ))}
                      </div>

                      {r.reasons && r.reasons.length > 0 && (
                        <div className="mb-2">
                          {r.reasons.map((rn, j) => <span key={j} className="inline-block text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded mr-1 mb-1">✅ {rn}</span>)}
                        </div>
                      )}
                      {r.risks && r.risks.length > 0 && (
                        <div className="mb-3">
                          {r.risks.map((rk, j) => <span key={j} className="inline-block text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded mr-1 mb-1">⚠️ {rk}</span>)}
                        </div>
                      )}

                      <div className="flex gap-2">
                        <button onClick={() => simFromListing(r)}
                          className="flex-1 py-1.5 text-xs bg-emerald-50 text-primary-strong border border-emerald-200 rounded-lg hover:bg-emerald-100">
                          📈 시뮬레이션
                        </button>
                        <button onClick={() => addToBasket(r)}
                          disabled={!!basket.find(b => b.listing.listing_id === r.listing.listing_id)}
                          className="flex-1 py-1.5 text-xs bg-slate-50 text-slate-700 border border-slate-200 rounded-lg hover:bg-slate-100 disabled:opacity-40">
                          {basket.find(b => b.listing.listing_id === r.listing.listing_id) ? "✓ 바구니 담김" : "➕ 비교 바구니"}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {tab === 1 && (
                <div className="bg-white rounded-xl shadow p-6 prose text-sm text-slate-700 whitespace-pre-wrap">
                  {report || "리포트 없음"}
                </div>
              )}
            </>
          )}
          </>)}
        </div>

        {/* 비교 바구니 사이드바 */}
        {basket.length > 0 && (
          <div className="w-56 shrink-0">
            <div className="bg-white rounded-xl shadow p-4 sticky top-6">
              <h3 className="font-semibold text-sm mb-3">⚖️ 비교 바구니 ({basket.length})</h3>
              <div className="space-y-2 mb-3">
                {basket.map(b => (
                  <div key={b.listing.listing_id} className="text-xs bg-slate-50 rounded p-2">
                    <div className="font-medium truncate">{b.listing.complex_name || b.listing.address}</div>
                    <div className="text-slate-400">{(b.listing.asking_price / 100000000).toFixed(1)}억</div>
                  </div>
                ))}
              </div>
              <button onClick={goCompare}
                className="w-full py-2 bg-primary text-white text-xs rounded-lg font-semibold hover:bg-primary-strong">
                비교 분석 시작
              </button>
              <button onClick={() => { setBasket([]); removeSessionValue("comparisonBasket"); }}
                className="w-full py-1.5 text-xs text-slate-400 mt-1 hover:text-slate-600">
                바구니 초기화
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
