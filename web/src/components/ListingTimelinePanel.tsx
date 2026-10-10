"use client";
import type { ListingMarketOverlay, ListingTimeline } from "@/lib/listings";
import ListingMarketChart from "@/components/ListingMarketChart";

const STATUS: Record<string, string> = { active: "거래 가능(제공자 표시)", withdrawn: "철회", completed: "거래 완료(제공자 표시)", unknown: "상태 미확인" };
const OUTCOME: Record<string, string> = { observed: "원문 읽음", blocked: "접근 제한", unavailable: "원문 확인 불가", failed: "조회 실패", parse_error: "판독 실패" };
const KEY_LABEL: Record<string, string> = { asking_price: "희망가", deposit: "보증금", monthly_rent: "월세" };
const won = (value: number | null | undefined) => value == null ? "—" : value >= 100_000_000 ? `${(value / 100_000_000).toFixed(2)}억` : `${Math.round(value / 10_000).toLocaleString()}만원`;
const day = (iso: string | null | undefined) => iso ? new Date(iso).toLocaleDateString("ko-KR") : "—";

function Spark({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const low = Math.min(...values), high = Math.max(...values), span = high - low || 1;
  const x = (i: number) => 4 + (i / (values.length - 1)) * 232;
  const y = (v: number) => 4 + (1 - (v - low) / span) * 40;
  // 저장한 시점 사이는 값이 유지된다고 보고 계단형으로 그린다. 관측하지 않은 중간 값을 추정해 잇지 않는다.
  const path = `M${x(0).toFixed(1)},${y(values[0]).toFixed(1)}` + values.slice(1).map((v, i) => ` H${x(i + 1).toFixed(1)} V${y(v).toFixed(1)}`).join("");
  return <svg role="img" aria-label="저장한 확인값의 변화" viewBox="0 0 240 48" className="h-12 w-full max-w-sm text-primary"><path d={path} fill="none" stroke="currentColor" strokeWidth="2" />
    {values.map((v, i) => <circle key={i} cx={x(i)} cy={y(v)} r="2.5" fill="currentColor" />)}</svg>;
}

export default function ListingTimelinePanel({ value, overlay, onClose }: { value: ListingTimeline; overlay?: ListingMarketOverlay | null; onClose: () => void }) {
  const primary = value.metrics[0];
  const primaryValues = primary ? value.points.map(p => p[primary.key as "asking_price" | "deposit" | "monthly_rent"]).filter((v): v is number => v != null) : [];
  return <section aria-label="매물 타임라인" className="space-y-3 rounded border bg-white p-4 text-sm break-words">
    <div className="flex items-start justify-between gap-3"><h2 className="font-bold">매물 타임라인 · 서비스 관측기간</h2><button className="underline" onClick={onClose}>닫기</button></div>
    {!value.period ? <p className="text-slate-600">저장된 확인 이력이 없습니다.</p> : <>
      <p>최초 저장 확인 {day(value.period.first_confirmed_at)} → 마지막 확인 {day(value.period.last_confirmed_at)} ({value.period.days}일 · 저장 {value.period.saved_versions}회){value.needs_confirmation && <span className="ml-2 rounded bg-amber-50 px-2 py-0.5 text-amber-900">재확인 필요</span>}</p>
      {value.metrics.map(m => <div key={m.key} className="rounded bg-slate-50 p-3">
        <p className="font-semibold">{m.label}: {won(m.initial)} → {won(m.current)}{m.cumulative_change_pct != null && ` (${m.cumulative_change_pct > 0 ? "+" : ""}${m.cumulative_change_pct}%)`}</p>
        <p className="text-xs text-slate-600">저장한 값이 바뀐 횟수 {m.change_count}회 · 최저 {won(m.lowest)} · 최고 {won(m.highest)}</p>
      </div>)}
      {overlay ? <ListingMarketChart overlay={overlay} timeline={value} /> : primary && <Spark values={primaryValues} />}
      {value.status_changes.length > 0 && <div><h3 className="font-semibold">저장한 상태 변경</h3><ul className="list-inside list-disc">{value.status_changes.map(c => <li key={c.at}>{day(c.at)} · {STATUS[c.from] ?? c.from} → {STATUS[c.to] ?? c.to}</li>)}</ul></div>}
    </>}
    <div><h3 className="font-semibold">원문 수집 시도</h3>
      {value.collection.attempts === 0 ? <p className="text-slate-600">수집 시도 기록이 없습니다.</p> : <>
        <p className="text-xs text-slate-600">시도 {value.collection.attempts}회 · 원문 읽음 {value.collection.observed}회 · 읽지 못함 {value.collection.unreadable}회 — 읽지 못한 시도는 거래 완료나 가격 변경을 뜻하지 않습니다.</p>
        <ul className="mt-1 space-y-1">{value.collection.recent.map(r => <li key={r.fetched_at}>{day(r.fetched_at)} · {OUTCOME[r.outcome] ?? r.outcome}
          {r.differs_from_saved && <span className="ml-1 text-amber-900"> · 원문 표시값이 저장값과 다름({r.differing_fields?.map(k => `${KEY_LABEL[k] ?? k} ${won(r[`observed_${k}` as "observed_asking_price"])}`).join(", ")}) — 확인 후 직접 저장해야 반영됩니다</span>}</li>)}</ul></>}
    </div>
    {value.limitations.map(text => <p key={text} className="text-xs text-slate-600">{text}</p>)}
  </section>;
}
