"use client";
import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { removeSessionValue, setSessionValue, useSessionValue } from "@/lib/sessionStore";
import type { RecommendationResult, ComparisonResult } from "@/lib/types";

function fmt(n?: number) { return n != null ? n.toLocaleString("ko-KR") + "원" : "—"; }
function fmtPct(n?: number) { return n != null ? (n >= 0 ? "+" : "") + n.toFixed(2) + "%" : "—"; }

export default function ComparisonPage() {
  const router = useRouter();
  const [result, setResult]   = useState<ComparisonResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState("");
  const [tab, setTab]         = useState(0);

  // 바구니는 sessionStorage 가 유일한 출처다 — 별도 state 로 복제하지 않고
  // 파생시킨다. 쓰기(setSessionValue/removeSessionValue)가 구독자에게 알리므로
  // 목록 변경이 그대로 리렌더로 이어진다.
  const rawBasket = useSessionValue("comparisonBasket");
  const basket = useMemo<RecommendationResult[]>(
    () => (rawBasket ? (JSON.parse(rawBasket) as RecommendationResult[]) : []),
    [rawBasket],
  );

  const handleCompare = async () => {
    if (basket.length < 2) { setError("최소 2개 이상 선택해야 합니다."); return; }
    setError("");
    setLoading(true);
    try {
      const listings = basket.map(b => b.listing);
      const recs     = basket;
      const res = await api.comparison(listings, recs) as { result?: ComparisonResult; report?: string; error?: string };
      if (res.error) throw new Error(res.error);
      if (res.result) {
        setResult({ ...res.result, decision_report: res.report || res.result.decision_report });
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "비교 분석 실패");
    } finally {
      setLoading(false);
    }
  };

  const clearBasket = () => {
    setResult(null);
    removeSessionValue("comparisonBasket");
  };

  const removeItem = (id: string) => {
    const next = basket.filter(b => b.listing.listing_id !== id);
    setSessionValue("comparisonBasket", JSON.stringify(next));
  };

  const simFromListing = (listing: RecommendationResult["listing"]) => {
    setSessionValue("simFromListing", JSON.stringify(listing));
    router.push("/simulation");
  };

  // undefined = 아직 클라이언트에서 읽기 전 — "바구니가 비어있습니다"가
  // 한 번 스쳤다 사라지지 않도록 아무것도 그리지 않는다.
  if (rawBasket === undefined) return null;

  if (basket.length === 0) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20">
        <div className="text-5xl mb-4">⚖️</div>
        <h2 className="text-xl font-semibold mb-2">비교 바구니가 비어있습니다</h2>
        <p className="text-slate-500 text-sm mb-4">이 화면은 샘플 매물 비교 도구입니다. 등록한 실제 후보는 매수 검토 케이스에서 비교하세요.</p>
        <button onClick={() => router.push("/cases")} className="mb-4 block w-full text-sm font-semibold text-primary underline">내 케이스에서 후보 비교하기 →</button>
        <button onClick={() => router.push("/recommendation")}
          className="px-6 py-2.5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-strong">
          단지 추천·샘플로 이동
        </button>
      </div>
    );
  }

  const winner = result?.rows?.find(r => r.is_winner);

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold">샘플 매물 비교</h1>
          <p className="text-slate-500 text-sm mt-1">{basket.length}개 매물 비교 분석</p>
        </div>
        <div className="flex gap-2">
          <button onClick={clearBasket} className="px-4 py-2 text-sm border border-slate-300 rounded-lg text-slate-500 hover:bg-slate-50">
            🗑️ 바구니 초기화
          </button>
          <button onClick={handleCompare} disabled={loading || basket.length < 2}
            className="px-5 py-2 text-sm bg-primary text-white rounded-lg font-semibold hover:bg-primary-strong disabled:opacity-50">
            {loading ? "분석 중..." : "📊 비교 분석 실행"}
          </button>
        </div>
      </div>

      {error && <p className="text-red-500 text-sm mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-2">⚠️ {error}</p>}

      {/* 바구니 목록 */}
      <div className="bg-white rounded-xl shadow p-4 mb-5">
        <h2 className="font-semibold text-sm mb-3 text-slate-600">비교 매물 ({basket.length}/5)</h2>
        <div className="flex flex-wrap gap-3">
          {basket.map((b, i) => (
            <div key={b.listing.listing_id} className="flex items-center gap-2 bg-slate-50 rounded-lg px-3 py-2 text-sm">
              <span className="text-xs text-primary font-bold">{i + 1}</span>
              <div>
                <div className="font-medium">{b.listing.complex_name || b.listing.address}</div>
                <div className="text-xs text-slate-400">{(b.listing.asking_price / 100000000).toFixed(1)}억 · 점수 {b.total_score?.toFixed(1) || "—"}</div>
              </div>
              <button onClick={() => removeItem(b.listing.listing_id)} className="text-slate-300 hover:text-red-400 ml-1">✕</button>
            </div>
          ))}
        </div>
      </div>

      {/* 비교 결과 */}
      {result && (
        <>
          {/* 우승 카드 */}
          {winner && (
            <div className="bg-gradient-to-r from-primary to-primary-strong text-white rounded-xl p-5 mb-5">
              <div className="text-sm opacity-80 mb-1">🏆 최우선 추천 매물</div>
              <h2 className="text-xl font-bold">{winner.listing.complex_name || winner.listing.address}</h2>
              <div className="text-sm opacity-90 mt-1">{winner.listing.address}</div>
              <div className="flex gap-6 mt-3 text-sm">
                <div><div className="opacity-70">가격</div><div className="font-semibold">{fmt(winner.listing.asking_price)}</div></div>
                {winner.total_score && <div><div className="opacity-70">종합 점수</div><div className="font-semibold">{winner.total_score.toFixed(1)}/10</div></div>}
              </div>
            </div>
          )}

          {/* 탭 */}
          <div className="flex border-b border-slate-200 mb-4 gap-1">
            {["📋 비교 테이블", "🏠 매물 상세", "📄 결정 리포트"].map((t, i) => (
              <button key={i} onClick={() => setTab(i)}
                className={`px-4 py-2 text-sm font-medium ${tab === i ? "tab-active" : "text-slate-500 hover:text-slate-700"}`}>{t}</button>
            ))}
          </div>

          {/* TAB 0: 비교 테이블 */}
          {tab === 0 && (
            <div className="bg-white rounded-xl shadow overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-slate-600 font-semibold">항목</th>
                    {result.rows.map(r => (
                      <th key={r.listing.listing_id} className={`px-4 py-3 text-left font-semibold ${r.is_winner ? "text-primary" : "text-slate-600"}`}>
                        {r.is_winner && "🏆 "}
                        {r.listing.complex_name || r.listing.address}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {[
                    { label: "순위", get: (r: typeof result.rows[0]) => `${r.rank}위${r.is_winner ? " 🏆" : ""}` },
                    { label: "가격", get: (r: typeof result.rows[0]) => fmt(r.listing.asking_price) },
                    { label: "종합 점수", get: (r: typeof result.rows[0]) => r.total_score?.toFixed(1) || "—" },
                    { label: "면적", get: (r: typeof result.rows[0]) => r.listing.area_m2 ? `${r.listing.area_m2.toFixed(1)}㎡` : "—" },
                    { label: "준공연도", get: (r: typeof result.rows[0]) => r.listing.built_year ? `${r.listing.built_year}년` : "—" },
                    { label: "역 거리", get: (r: typeof result.rows[0]) => r.listing.station_distance_m ? `${r.listing.station_distance_m}m` : "—" },
                    { label: "연환산 수익률", get: (r: typeof result.rows[0]) => r.simulation_result ? fmtPct(r.simulation_result.scenario_base.annual_equity_roi) : "—" },
                  ].map(({ label, get }) => (
                    <tr key={label} className="hover:bg-slate-50">
                      <td className="px-4 py-2.5 text-slate-500 font-medium">{label}</td>
                      {result.rows.map(r => (
                        <td key={r.listing.listing_id} className={`px-4 py-2.5 ${r.is_winner ? "font-semibold text-primary-strong" : ""}`}>
                          {get(r)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* TAB 1: 매물 상세 */}
          {tab === 1 && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {result.rows.map(r => (
                <div key={r.listing.listing_id} className={`bg-white rounded-xl shadow p-5 ${r.is_winner ? "ring-2 ring-primary/60" : ""}`}>
                  <div className="flex justify-between items-start mb-3">
                    <div>
                      {r.is_winner && <span className="text-xs text-primary bg-emerald-50 px-2 py-0.5 rounded-full font-bold mb-1 inline-block">추천</span>}
                      <h3 className="font-bold">{r.listing.complex_name || r.listing.address}</h3>
                      <p className="text-xs text-slate-400">{r.listing.address}</p>
                    </div>
                    <div className="text-right">
                      <div className="font-bold text-primary-strong">{fmt(r.listing.asking_price)}</div>
                      {r.total_score && <div className="text-xs text-slate-500">점수 {r.total_score.toFixed(1)}</div>}
                    </div>
                  </div>
                  {r.highlights && r.highlights.length > 0 && (
                    <div className="mb-2">{r.highlights.map((h, i) => <span key={i} className="inline-block text-xs bg-green-50 text-green-700 px-2 py-0.5 rounded mr-1 mb-1">✅ {h}</span>)}</div>
                  )}
                  {r.warnings && r.warnings.length > 0 && (
                    <div className="mb-3">{r.warnings.map((w, i) => <span key={i} className="inline-block text-xs bg-red-50 text-red-600 px-2 py-0.5 rounded mr-1 mb-1">⚠️ {w}</span>)}</div>
                  )}
                  <button onClick={() => simFromListing(r.listing)}
                    className="w-full py-1.5 text-xs bg-emerald-50 text-primary-strong border border-emerald-200 rounded-lg hover:bg-emerald-100">
                    📈 이 매물로 시뮬레이션
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* TAB 2: 결정 리포트 */}
          {tab === 2 && (
            <div className="bg-white rounded-xl shadow p-6 prose text-sm text-slate-700 whitespace-pre-wrap">
              {result.decision_report || "리포트 없음"}
            </div>
          )}
        </>
      )}
    </div>
  );
}
