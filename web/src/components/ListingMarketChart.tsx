"use client";
import type { ListingMarketOverlay, ListingTimeline } from "@/lib/listings";

const eok = (value: number) => `${(value / 100_000_000).toFixed(2)}억`;
const manwon = (value: number) => `${Math.round(value / 10_000).toLocaleString()}만원`;
const time = (iso: string) => new Date(iso.length === 19 ? iso.replace(" ", "T") : iso).getTime();
const SUMMARY: Record<string, string> = {
  no_trades: "연결된 같은 단지·비슷한 면적의 거래가 없어 비교하지 않았습니다.",
  insufficient: "최근 6개월 거래가 3건 미만이라 호가와의 차이를 계산하지 않았습니다.",
  no_asking: "저장된 호가나 면적이 없어 비교하지 않았습니다.",
};

export default function ListingMarketChart({ overlay, timeline }: { overlay: ListingMarketOverlay; timeline: ListingTimeline }) {
  if (!overlay.applicable) return <p className="rounded bg-slate-50 p-3 text-xs text-slate-600">실거래 겹쳐 보기: {overlay.reason}</p>;
  const trades = overlay.trades?.trades ?? [];
  const asking = timeline.points.filter(p => p.asking_price != null).map(p => ({ t: time(p.confirmed_at), v: p.asking_price as number }));
  const avm = overlay.avm.filter(a => a.shown && a.estimated_value_won != null && a.analyzed_at)
    .map(a => ({ t: time(a.analyzed_at), v: a.estimated_value_won as number, stale: a.status !== "completed" }));
  const tradePoints = trades.map(t => ({ t: time(t.deal_date), v: t.price_won, label: `${t.deal_date} · ${t.floor ? t.floor + "층 · " : ""}${t.area_sqm}㎡ · ${eok(t.price_won)}` }));
  const times = [...asking.map(p => p.t), ...avm.map(p => p.t), ...tradePoints.map(p => p.t)].filter(Number.isFinite);
  const values = [...asking.map(p => p.v), ...avm.map(p => p.v), ...tradePoints.map(p => p.v)];
  if (times.length < 1 || values.length < 1) return <p className="rounded bg-slate-50 p-3 text-xs text-slate-600">그릴 수 있는 가격 자료가 없습니다.</p>;
  const t0 = Math.min(...times), t1 = Math.max(...times, asking.length ? asking[asking.length - 1].t : 0);
  const v0 = Math.min(...values), v1 = Math.max(...values);
  const pad = (v1 - v0) * 0.1 || v1 * 0.05;
  const x = (t: number) => 44 + (t1 === t0 ? 0.5 : (t - t0) / (t1 - t0)) * 300;
  const y = (v: number) => 8 + (1 - (v - (v0 - pad)) / (v1 - v0 + 2 * pad)) * 130;
  // 저장한 시점 사이는 값이 유지되었다고 보는 계단형이다. 거래·AVM 점은 서로 다른 자료라 선으로 잇지 않는다.
  const step = asking.length
    ? `M${x(asking[0].t).toFixed(1)},${y(asking[0].v).toFixed(1)}` + asking.slice(1).map(p => ` H${x(p.t).toFixed(1)} V${y(p.v).toFixed(1)}`).join("") + ` H${x(t1).toFixed(1)}`
    : "";
  const summary = overlay.summary;
  const hidden = overlay.avm.filter(a => !a.shown).length;
  return <div className="space-y-2">
    <svg role="img" aria-label="호가 이력과 같은 단지 실거래, 저장된 AVM 비교" viewBox="0 0 360 170" className="w-full max-w-xl">
      <text x="2" y="14" fontSize="9" fill="currentColor">{eok(v1 + pad)}</text>
      <text x="2" y="138" fontSize="9" fill="currentColor">{eok(v0 - pad)}</text>
      <line x1="44" x2="344" y1="140" y2="140" stroke="#94a3b8" strokeWidth="1" />
      {step && <path d={step} fill="none" stroke="#2563eb" strokeWidth="2" />}
      {asking.map((p, i) => <circle key={`a${i}`} cx={x(p.t)} cy={y(p.v)} r="3" fill="#2563eb"><title>{`호가 ${eok(p.v)}`}</title></circle>)}
      {tradePoints.map((p, i) => <circle key={`t${i}`} cx={x(p.t)} cy={y(p.v)} r="2.6" fill="#64748b" fillOpacity="0.7"><title>{p.label}</title></circle>)}
      {avm.map((p, i) => <rect key={`v${i}`} x={x(p.t) - 4} y={y(p.v) - 4} width="8" height="8" transform={`rotate(45 ${x(p.t)} ${y(p.v)})`}
        fill={p.stale ? "#fff" : "#d97706"} stroke="#d97706" strokeWidth="1.5"><title>{`저장된 AVM ${eok(p.v)}${p.stale ? " (오래된 분석)" : ""}`}</title></rect>)}
      <text x="44" y="156" fontSize="9" fill="currentColor">{new Date(t0).toLocaleDateString("ko-KR")}</text>
      <text x="344" y="156" fontSize="9" fill="currentColor" textAnchor="end">{new Date(t1).toLocaleDateString("ko-KR")}</text>
    </svg>
    <p className="flex flex-wrap gap-x-4 text-xs text-slate-600">
      <span><b className="text-blue-600">━●</b> 저장한 호가</span>
      <span><b className="text-slate-500">●</b> 같은 단지 실거래 {trades.length}건</span>
      <span><b className="text-amber-600">◆</b> 저장된 AVM{avm.length === 0 ? "(표시할 값 없음)" : ""}</span>
    </p>
    {summary.status === "ok" && summary.recent_median_per_sqm_won != null && summary.asking_vs_recent_median_pct != null
      ? <p>최근 {summary.recent_window_months}개월 같은 단지 {summary.recent_count}건의 ㎡당 중앙값 {manwon(summary.recent_median_per_sqm_won)} 대비 호가는 {summary.asking_vs_recent_median_pct > 0 ? "+" : ""}{summary.asking_vs_recent_median_pct}% (시점·층·향 보정 없음)</p>
      : <p className="text-slate-600">{SUMMARY[summary.status] ?? ""}</p>}
    {overlay.trades && !overlay.trades.available && overlay.trades.reason && <p className="text-xs text-amber-800">{overlay.trades.reason}</p>}
    {overlay.trades?.data_through && <p className="text-xs text-slate-600">저장된 실거래의 마지막 거래월 {overlay.trades.data_through}{overlay.trades.match === "partial_unique" ? " · 단지명이 부분 일치로 연결됨" : ""}</p>}
    {hidden > 0 && <p className="text-xs text-slate-600">시장가격 비교 기준을 통과하지 못한 AVM 분석 {hidden}건은 가격을 표시하지 않았습니다.</p>}
    {overlay.limitations.map(text => <p key={text} className="text-xs text-slate-600">{text}</p>)}
  </div>;
}
