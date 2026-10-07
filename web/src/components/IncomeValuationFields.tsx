import type { IncomeValuationInput } from "@/lib/valuation";

export type IncomeDraft = { rent: string; minCost: string; maxCost: string; minCap: string; maxCap: string; asking: string; scope: string };
export const emptyIncomeDraft: IncomeDraft = { rent: "", minCost: "", maxCost: "", minCap: "", maxCap: "", asking: "", scope: "" };

export function incomeInput(draft: IncomeDraft, date: string): IncomeValuationInput {
  const amount = (value: string, optional = false) => {
    if (!value.trim()) { if (optional) return null; throw new Error("현재 받는 월세를 입력해주세요. 공실이면 0을 입력하세요."); }
    const number = Number(value);
    if (!Number.isSafeInteger(number) || number < 0 || number > 1e15) throw new Error("금액은 0 이상의 원 단위 정수로 입력해주세요.");
    return number;
  };
  const rent = amount(draft.rent);
  const minCost = amount(draft.minCost, true), maxCost = amount(draft.maxCost, true);
  const asking = amount(draft.asking, true);
  const minCap = Number(draft.minCap), maxCap = Number(draft.maxCap);
  if ((minCost == null) !== (maxCost == null) || (minCost != null && maxCost != null && minCost > maxCost)) throw new Error("월 운영비 최소·최대값을 함께 입력하고 범위를 확인해주세요.");
  if (!draft.minCap || !draft.maxCap || !Number.isFinite(minCap) || !Number.isFinite(maxCap) || minCap < 0.1 || maxCap > 100 || minCap > maxCap) throw new Error("환원율 가정의 최소·최대값을 0.1~100% 범위로 입력해주세요.");
  if (asking === 0) throw new Error("매매 호가는 0보다 커야 합니다. 모르면 비워두세요.");
  if (draft.scope !== "single_unit" && draft.scope !== "whole_building") throw new Error("임대료에 해당하는 평가 범위를 선택해주세요.");
  return { monthly_rent_won: rent ?? 0, monthly_operating_cost_min_won: minCost, monthly_operating_cost_max_won: maxCost,
    cap_rate_min_pct: minCap, cap_rate_max_pct: maxCap, asking_price_won: asking, valuation_unit: draft.scope, as_of_date: date };
}

export default function IncomeValuationFields({ draft, onChange }: { draft: IncomeDraft; onChange: (value: IncomeDraft) => void }) {
  const input = "mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2";
  const fields: [keyof IncomeDraft, string, string][] = [["rent", "현재 받는 월세 합계(원)", "부가세·관리비·보증금 제외"],
    ["minCost", "월 소유자 운영비 최소(원)", "미확인 시 최소·최대 모두 비워두기"], ["maxCost", "월 소유자 운영비 최대(원)", "확정 비용이면 최소와 같은 금액"],
    ["minCap", "가정 환원율 최소(%)", "사용자가 정하는 가정"], ["maxCap", "가정 환원율 최대(%)", "실측 시장 환원율이 아님"],
    ["asking", "매매 호가(원, 선택)", "입력하면 호가 대비 수익률 표시"]];
  return <section className="mb-5 space-y-4 rounded-xl border border-emerald-200 bg-emerald-50/40 p-4" aria-label="임대료 수익 분석 입력">
    <h3 className="font-semibold">현재 임대료로 수익·가격 범위 검토</h3>
    <label className="block text-sm">평가 범위<select aria-label="평가 범위" className={input} value={draft.scope} onChange={e => onChange({ ...draft, scope: e.target.value })}>
      <option value="">범위 선택</option><option value="single_unit">개별 호실</option><option value="whole_building">건물 전체</option>
    </select></label>
    <div className="grid gap-4 sm:grid-cols-2">{fields.map(([key, label, hint]) => <label key={key} className="block text-sm">{label}
      <input aria-label={label} type="number" min={key.includes("Cap") ? "0.1" : "0"} step={key.includes("Cap") ? "0.01" : "1"} value={draft[key]} className={input} onChange={e => onChange({ ...draft, [key]: e.target.value })} />
      <span className="mt-1 block text-xs text-slate-500">{hint}</span>
    </label>)}</div>
    <p className="text-xs text-slate-600">현재 받는 월세를 연 환산하므로 공실 손실을 다시 빼지 않습니다. 소유자 운영비에는 대출 원리금·취득세·대수선비를 넣지 마세요. 운영비 미입력 시 순수익과 가격 산출은 보류합니다.</p>
    <p className="text-xs text-slate-600">환원율 범위는 비교를 위한 가정입니다. 보증금 운용수익과 반환 의무는 이 가격 시나리오에 반영하지 않습니다.</p>
  </section>;
}
