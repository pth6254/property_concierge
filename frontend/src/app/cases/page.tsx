"use client";

import Link from "next/link";
import DecisionJourney from "@/components/DecisionJourney";
import { useEffect, useState } from "react";
import { BriefcaseBusiness, ChevronRight, Plus } from "lucide-react";
import { api } from "@/lib/api";
import type { PurchaseCase } from "@/lib/types";

const STATUS: Record<string, string> = {
  exploring: "지역 탐색", reviewing: "후보 검토", negotiating: "협상", decided: "결정", archived: "보관",
};

export default function CasesPage() {
  const [cases, setCases] = useState<PurchaseCase[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [region, setRegion] = useState("");
  const [budget, setBudget] = useState("");
  const [error, setError] = useState("");

  const load = async () => {
    const result = await api.cases();
    setCases(result.items);
  };

  useEffect(() => {
    let cancelled = false;
    api.cases().then((result) => { if (!cancelled) setCases(result.items); })
      .catch(() => { if (!cancelled) setError("케이스 목록을 불러오지 못했습니다."); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await api.createCase({
        title: title.trim(),
        budget_max: budget ? Number(budget) * 10_000 : undefined,
        target_regions: region.trim() ? [region.trim()] : [],
      });
      setTitle(""); setRegion(""); setBudget(""); setOpen(false);
      await load();
    } catch {
      setError("케이스를 만들지 못했습니다. 입력값을 확인해주세요.");
    }
  };

  return (
    <div className="mx-auto max-w-6xl">
      <DecisionJourney current="cases" />
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">매수 검토 케이스</h1>
          <p className="mt-1 text-sm text-slate-500">후보 매물과 시세추정 결과를 한 의사결정 흐름으로 관리합니다.</p>
        </div>
        <button onClick={() => setOpen((value) => !value)} className="flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-strong">
          <Plus size={16} /> 새 케이스
        </button>
      </div>

      {open && (
        <form onSubmit={create} className="mb-6 grid gap-3 rounded-xl border border-emerald-100 bg-white p-5 shadow-sm md:grid-cols-3">
          <input required maxLength={150} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예: 서초구 실거주 매수" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          <input value={region} onChange={(e) => setRegion(e.target.value)} placeholder="선호 지역" className="rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          <div className="flex gap-2">
            <input min="0" type="number" value={budget} onChange={(e) => setBudget(e.target.value)} placeholder="최대 예산(만원)" className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
            <button className="rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">생성</button>
          </div>
        </form>
      )}
      {error && <p className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-600">{error}</p>}

      {loading ? <div className="py-16 text-center text-slate-400">불러오는 중...</div> : cases.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-300 bg-white py-16 text-center">
          <BriefcaseBusiness className="mx-auto mb-3 text-slate-300" size={36} />
          <p className="font-semibold text-slate-700">아직 검토 케이스가 없습니다.</p>
          <p className="mt-1 text-sm text-slate-400">매수 목표를 만들고 후보 부동산을 모아보세요.</p>
          <Link href="/explore" className="mt-4 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white">동네 탐색부터 시작</Link>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {cases.map((item) => (
            <Link key={item.id} href={`/cases/${item.id}`} className="group rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition hover:border-emerald-300 hover:shadow-md">
              <div className="flex items-start justify-between">
                <span className="rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-primary">{STATUS[item.status]}</span>
                <ChevronRight size={18} className="text-slate-300 group-hover:text-primary" />
              </div>
              <h2 className="mt-4 font-bold text-slate-900">{item.title}</h2>
              <p className="mt-2 text-sm text-slate-500">{item.target_regions.join(", ") || "지역 미정"}</p>
              <div className="mt-5 flex justify-between border-t border-slate-100 pt-4 text-sm">
                <span className="text-slate-500">후보 {item.property_count}개</span>
                <span className="font-semibold text-slate-700">{item.budget_max ? `${Math.round(item.budget_max / 10_000).toLocaleString()}만원` : "예산 미정"}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
