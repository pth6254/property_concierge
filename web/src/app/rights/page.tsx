"use client";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { removeSessionValue, useSessionValue } from "@/lib/sessionStore";

type RightsResult = Awaited<ReturnType<typeof api.rightsAnalyze>>;

function parsePrice(s: string): number {
  if (!s.trim()) return 0;
  const n = s
    .replace(/억/g, "00000000")
    .replace(/천만/g, "0000000")
    .replace(/천/g, "0000")
    .replace(/만/g, "0000")
    .replace(/[^0-9]/g, "");
  return n ? parseInt(n) : 0;
}

function fmt(n?: number) { return n != null ? n.toLocaleString("ko-KR") + "원" : "—"; }

function fileToB64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));   // dataURL — 서버가 접두사 처리
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

const GRADE_STYLE: Record<string, string> = {
  danger:  "bg-red-50 border-red-300 text-red-800",
  caution: "bg-amber-50 border-amber-300 text-amber-800",
  safe:    "bg-emerald-50 border-emerald-300 text-emerald-800",
};

type CandidateSeed = { case_id?: number; candidate_id?: number; market_price?: number; address?: string };

export default function RightsPage() {
  const rawSeed = useSessionValue("rightsCandidate");
  return <RightsForm key={rawSeed ?? "no-seed"} rawSeed={rawSeed ?? null} />;
}

function RightsForm({ rawSeed }: { rawSeed: string | null }) {
  const seed = useMemo<CandidateSeed>(() => rawSeed ? JSON.parse(rawSeed) as CandidateSeed : {}, [rawSeed]);
  useEffect(() => () => removeSessionValue("rightsCandidate"), []);
  const [registryFile, setRegistryFile] = useState<File | null>(null);
  const [buildingFile, setBuildingFile] = useState<File | null>(null);
  const [depositStr, setDepositStr] = useState("");
  const [priceStr, setPriceStr] = useState(seed.market_price ? String(Math.round(seed.market_price / 10_000)) + "만" : "");
  const [result, setResult] = useState<RightsResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async () => {
    if (!registryFile && !buildingFile) { setError("등기부등본 또는 건축물대장 PDF를 업로드해주세요."); return; }
    setError("");
    setLoading(true);
    setResult(null);
    try {
      const res = await api.rightsAnalyze({
        case_id: seed.case_id,
        candidate_id: seed.candidate_id,
        registry_pdf_b64: registryFile ? await fileToB64(registryFile) : undefined,
        building_pdf_b64: buildingFile ? await fileToB64(buildingFile) : undefined,
        my_deposit: parsePrice(depositStr),
        market_price: parsePrice(priceStr),
      });
      if (res.error) throw new Error(res.error);
      setResult(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "분석 실패");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto">
      {seed.address && <div className="mb-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-800">검토 후보: {seed.address} · 문서를 업로드해야 분석 결과가 연결됩니다.</div>}
      <h1 className="text-2xl font-bold mb-1">권리관계 위험 점검</h1>
      <p className="text-slate-500 text-sm mb-2">
        등기부등본·건축물대장 PDF를 업로드하면 가압류·근저당·깡통전세 등 위험 신호를 점검합니다.
      </p>
      <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-3 py-2 rounded-lg mb-2">
        참고용 자동 점검이며 법률사무(권리분석)가 아닙니다. 계약 전 반드시 공인중개사·법무사 확인을 거치세요.
      </p>
      <p className="text-xs text-ink-muted bg-emerald-50 border border-emerald-200 px-3 py-2 rounded-lg mb-5">
        업로드한 PDF는 메모리에서만 분석되고 즉시 파기되며, 서버에 저장되지 않습니다.
        분석 기록에는 상세 주소 대신 마스킹된 주소만 남습니다.
      </p>

      {/* 입력 */}
      <div className="bg-white rounded-xl shadow p-5 mb-5 space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              등기사항전부증명서 PDF <span className="text-slate-400">(인터넷등기소 발급 원본)</span>
            </label>
            <input type="file" accept=".pdf" className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2"
              onChange={e => setRegistryFile(e.target.files?.[0] || null)} />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              건축물대장 PDF <span className="text-slate-400">(정부24 발급, 선택)</span>
            </label>
            <input type="file" accept=".pdf" className="w-full text-sm border border-slate-300 rounded-lg px-3 py-2"
              onChange={e => setBuildingFile(e.target.files?.[0] || null)} />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">내 보증금 (전세·월세 보증금)</label>
            <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 3억"
              value={depositStr} onChange={e => setDepositStr(e.target.value)} />
          </div>
          <div>
            <label className="block text-xs text-slate-500 mb-1">
              시세 <span className="text-slate-400">(AI 시세추정 결과 또는 직접 입력)</span>
            </label>
            <input className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="예: 8억"
              value={priceStr} onChange={e => setPriceStr(e.target.value)} />
          </div>
        </div>
        <button onClick={handleSubmit} disabled={loading}
          className="w-full py-2.5 bg-primary text-white rounded-xl font-semibold text-sm hover:bg-primary-strong disabled:opacity-50">
          {loading ? "분석 중..." : "위험 점검 시작"}
        </button>
        {error && <p className="text-red-500 text-sm">{error}</p>}
      </div>

      {/* 결과 */}
      {result && (
        <div className="space-y-4">
          {/* 종합 등급 */}
          <div className={`rounded-xl border p-5 ${GRADE_STYLE[result.risk_grade]}`}>
            <div className="flex items-center justify-between">
              <div className="font-bold text-lg">
                {result.risk_grade === "danger" ? "🔴" : result.risk_grade === "caution" ? "🟡" : "🟢"} {result.risk_label}
              </div>
              <div className="text-sm">위험 점수 {result.risk_score} / 100</div>
            </div>
            {result.reasons.length > 0 && (
              <ul className="mt-3 space-y-1.5 text-sm">
                {result.reasons.map((r, i) => <li key={i}>{r}</li>)}
              </ul>
            )}
          </div>

          {/* 보증금 안전성 */}
          {result.deposit_safety?.available && (
            <div className="bg-white rounded-xl shadow p-5">
              <h3 className="font-semibold mb-3">보증금 안전성 (경매 배당 시뮬레이션)</h3>
              <table className="w-full text-sm">
                <tbody>
                  {([
                    ["선순위 채권 합계 (근저당 채권최고액 등)", fmt(result.deposit_safety.senior_total)],
                    ["선순위 + 내 보증금", fmt(result.deposit_safety.total_burden)],
                    ["시세 대비 부담률", `${(result.deposit_safety.burden_ratio * 100).toFixed(1)}% (${result.deposit_safety.label})`],
                    ["예상 낙찰가 (낙찰가율 80% 가정)", fmt(result.deposit_safety.expected_auction)],
                    ["경매 시 예상 보증금 회수액", fmt(result.deposit_safety.expected_recovery)],
                    ...(result.deposit_safety.recovery_shortfall > 0
                      ? [["예상 손실액", fmt(result.deposit_safety.recovery_shortfall)]] : []),
                  ] as [string, string][]).map(([k, v]) => (
                    <tr key={k} className="border-b border-slate-100">
                      <td className="py-1.5 text-slate-500">{k}</td>
                      <td className="py-1.5 text-right font-medium">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="text-xs text-slate-400 mt-2">
                소액임차인 최우선변제: {result.deposit_safety.small_tenant
                  ? `✅ 해당 (${result.deposit_safety.small_tenant_rule.region} 기준 ${fmt(result.deposit_safety.small_tenant_rule.priority_amount)}까지 우선 배당)`
                  : `해당 없음 (보증금이 ${result.deposit_safety.small_tenant_rule.region} 기준 ${fmt(result.deposit_safety.small_tenant_rule.limit)} 초과)`}
              </p>
            </div>
          )}

          {/* 등기부 요약 */}
          {result.registry && !result.registry.error && (
            <div className="bg-white rounded-xl shadow p-5">
              <h3 className="font-semibold mb-3">등기부 요약</h3>
              <table className="w-full text-sm">
                <tbody>
                  {([
                    ["소재지", result.registry.address || "—"],
                    ["소유자", result.registry.owner || "—"],
                    ["근저당 채권최고액 합계", `${fmt(result.registry.mortgage_total)} (${result.registry.mortgage_count}건)`],
                    ...(result.registry.senior_count
                      ? [["선순위 전세·임차 보증금", `${fmt(result.registry.senior_deposits)} (${result.registry.senior_count}건)`]] : []),
                  ] as [string, string][]).map(([k, v]) => (
                    <tr key={k} className="border-b border-slate-100">
                      <td className="py-1.5 text-slate-500 w-52">{k}</td>
                      <td className="py-1.5">{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* 건축물대장 */}
          {result.building && !result.building.error && (
            <div className="bg-white rounded-xl shadow p-5">
              <h3 className="font-semibold mb-3">건축물대장</h3>
              <div className="text-sm space-y-1">
                <p>위반건축물: {result.building.violation
                  ? <span className="text-red-600 font-semibold">위반건축물 표시 있음</span>
                  : "✅ 표시 없음"}</p>
                {result.building.main_use && <p className="text-slate-500">주용도: {result.building.main_use}</p>}
                {result.building.approval_date && <p className="text-slate-500">사용승인일: {result.building.approval_date}</p>}
              </div>
            </div>
          )}

          <p className="text-xs text-slate-400">{result.disclaimer}</p>
        </div>
      )}
    </div>
  );
}
