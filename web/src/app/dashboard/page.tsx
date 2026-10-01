"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";
import type { HistoryItem } from "@/lib/types";

const PAGE_SIZE = 20;
const VERDICT_COLOR: Record<string, string> = {
  저평가: "text-green-600", 고평가: "text-red-600", 적정가: "text-sky-600",
};

export default function DashboardPage() {
  const [items, setItems]         = useState<HistoryItem[]>([]);
  const [total, setTotal]         = useState(0);
  const [page, setPage]           = useState(0);
  const [keyword, setKeyword]     = useState("");
  const [search, setSearch]       = useState("");
  const [loading, setLoading]     = useState(true);
  const [selected, setSelected]   = useState<HistoryItem | null>(null);

  const load = async (p = 0, kw = "") => {
    setLoading(true);
    try {
      const res = await api.history(PAGE_SIZE, p * PAGE_SIZE, kw);
      setItems(res.items as HistoryItem[]);
      setTotal(res.total);
    } finally {
      setLoading(false);
    }
  };

  // 최초 목록 로드. load() 를 그대로 호출하면 그 안의 setLoading(true) 가
  // effect 본문에서 동기 실행되어 연쇄 렌더를 유발하므로(loading 은 이미 true 로
  // 시작한다) 여기서는 fetch 후 결과만 반영한다. 언마운트 시 setState 를
  // 건너뛰도록 취소 플래그도 함께 둔다.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await api.history(PAGE_SIZE, 0, "");
        if (cancelled) return;
        setItems(res.items as HistoryItem[]);
        setTotal(res.total);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const doSearch = () => { setPage(0); load(0, search); setKeyword(search); };

  const doDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    await api.deleteHistory(id);
    load(page, keyword);
  };

  // KPI
  const avgEst = items.reduce((s, it) => s + (it.estimated_value || 0), 0) / (items.length || 1);
  const underCount = items.filter(it => it.valuation_verdict?.includes("저평가")).length;

  // Charts
  const verdictData = ["저평가", "적정가", "고평가"].map(v => ({
    name: v, count: items.filter(it => it.valuation_verdict?.includes(v.replace("가", ""))).length,
  }));
  const gradeData = ["A+", "A", "B+", "B", "C"].map(g => ({
    name: g, count: items.filter(it => it.investment_grade === g).length,
  })).filter(d => d.count > 0);

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">이력 대시보드</h1>

      {/* KPI */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {[
          { label: "총 시세추정", value: total.toLocaleString() + "건" },
          { label: "평균 추정가", value: avgEst > 0 ? Math.round(avgEst / 10000).toLocaleString() + "만원" : "—" },
          { label: "저평가 매물", value: underCount + "건" },
          { label: "이번 페이지", value: items.length + "건" },
        ].map(({ label, value }) => (
          <div key={label} className="bg-white rounded-xl shadow p-4">
            <div className="text-xs text-slate-400">{label}</div>
            <div className="font-bold text-xl mt-1 text-slate-800">{value}</div>
          </div>
        ))}
      </div>

      {/* Charts */}
      {items.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
          <div className="bg-white rounded-xl shadow p-4">
            <h3 className="font-semibold text-sm mb-3 text-slate-600">고저평가 분포</h3>
            <ResponsiveContainer width="100%" height={140}>
              <BarChart data={verdictData}>
                <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          {gradeData.length > 0 && (
            <div className="bg-white rounded-xl shadow p-4">
              <h3 className="font-semibold text-sm mb-3 text-slate-600">투자 등급 분포</h3>
              <ResponsiveContainer width="100%" height={140}>
                <BarChart data={gradeData}>
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}

      {/* 검색 */}
      <div className="flex gap-2 mb-4">
        <input
          className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
          placeholder="키워드 검색..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          onKeyDown={e => e.key === "Enter" && doSearch()}
        />
        <button onClick={doSearch} className="px-4 py-2 bg-primary text-white rounded-lg text-sm hover:bg-primary-strong">검색</button>
        {keyword && (
          <button onClick={() => { setSearch(""); setKeyword(""); load(0, ""); }}
            className="px-3 py-2 text-sm text-slate-500 hover:text-slate-700">초기화</button>
        )}
      </div>

      {/* 테이블 */}
      <div className="bg-white rounded-xl shadow overflow-hidden mb-4">
        {loading ? (
          <div className="text-center py-10 text-slate-400">로딩 중...</div>
        ) : items.length === 0 ? (
          <div className="text-center py-10 text-slate-400">이력 없음</div>
        ) : (
          <table className="w-full text-sm">
            <thead className="bg-slate-50">
              <tr>
                {["#", "물건 정보", "유형", "추정가", "판정", "등급", "일시", ""].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-slate-600 font-semibold">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map(it => (
                <tr key={it.id} className="hover:bg-emerald-50 cursor-pointer" onClick={() => setSelected(selected?.id === it.id ? null : it)}>
                  <td className="px-4 py-3 text-slate-400">{it.id}</td>
                  <td className="px-4 py-3 max-w-[220px] truncate">{it.query}</td>
                  <td className="px-4 py-3">{it.category || "—"}</td>
                  <td className="px-4 py-3">
                    {it.estimated_value ? Math.round(it.estimated_value / 10000).toLocaleString() + "만원" : "—"}
                  </td>
                  <td className={`px-4 py-3 font-medium ${VERDICT_COLOR[it.valuation_verdict || ""] || "text-slate-700"}`}>
                    {it.valuation_verdict || "—"}
                  </td>
                  <td className="px-4 py-3">{it.investment_grade || "—"}</td>
                  <td className="px-4 py-3 text-slate-400 text-xs">{it.created?.slice(0, 16) || "—"}</td>
                  <td className="px-4 py-3 whitespace-nowrap">
                    <Link
                      href={`/report/${it.id}`}
                      onClick={e => e.stopPropagation()}
                      className="text-primary hover:text-primary-strong text-xs mr-3"
                    >
                      리포트
                    </Link>
                    <button onClick={e => doDelete(it.id, e)} className="text-red-400 hover:text-red-600 text-xs">삭제</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* 상세 패널 */}
      {selected && (
        <div className="bg-white rounded-xl shadow p-5 mb-4">
          <div className="flex justify-between items-center mb-3">
            <h3 className="font-semibold">상세 정보 — {selected.query}</h3>
            <button onClick={() => setSelected(null)} className="text-slate-400 hover:text-slate-600">✕</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            {[
              { label: "추정가", val: selected.estimated_value ? Math.round(selected.estimated_value / 10000).toLocaleString() + "만원" : "—" },
              { label: "판정", val: selected.valuation_verdict || "—" },
              { label: "등급", val: selected.investment_grade || "—" },
              { label: "Cap Rate", val: selected.cap_rate ? `${selected.cap_rate}%` : "—" },
            ].map(({ label, val }) => (
              <div key={label} className="bg-slate-50 rounded-lg p-3">
                <div className="text-xs text-slate-400">{label}</div>
                <div className="font-medium mt-0.5">{val}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 페이지네이션 */}
      {total > PAGE_SIZE && (
        <div className="flex gap-2 justify-center">
          <button disabled={page === 0} onClick={() => { setPage(p => p - 1); load(page - 1, keyword); }}
            className="px-4 py-2 text-sm bg-white border border-slate-300 rounded-lg disabled:opacity-40 hover:bg-slate-50">이전</button>
          <span className="px-4 py-2 text-sm text-slate-500">{page + 1} / {Math.ceil(total / PAGE_SIZE)}</span>
          <button disabled={(page + 1) * PAGE_SIZE >= total} onClick={() => { setPage(p => p + 1); load(page + 1, keyword); }}
            className="px-4 py-2 text-sm bg-white border border-slate-300 rounded-lg disabled:opacity-40 hover:bg-slate-50">다음</button>
        </div>
      )}
    </div>
  );
}
