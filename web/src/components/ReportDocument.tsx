"use client";
import Link from "next/link";
import type { ReactNode } from "react";
import type { EvidenceWindow } from "@/lib/valuation";

/*
 * 시세추정 리포트의 문서 틀(표지·절 제목·표·고지사항).
 * 시장가격 결과뿐 아니라 보류·조건부·공개자료 결과도 같은 문서 양식으로 보여주기 위해 분리했다.
 * 결과 종류에 따라 내용은 달라도 사용자가 인쇄·보관하는 형식은 같아야 한다.
 */

export function SectionTitle({ number, title }: { number: string; title: string }) {
  return (
    <div className="flex items-baseline gap-3 mb-3 pb-1.5 border-b-2 border-gray-700">
      <span className="text-[11px] font-medium text-gray-500 tracking-wide shrink-0">{number}</span>
      <h2 className="text-sm font-bold text-gray-900 tracking-wide">{title}</h2>
    </div>
  );
}

export type InfoRow = [string, ReactNode] | { divider: string };

export function InfoTable({ rows }: { rows: InfoRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <tbody>
          {rows.map((row, i) => {
            if ("divider" in row) {
              return (
                <tr key={i}>
                  <td colSpan={2} className="border border-gray-400 bg-gray-700 text-white px-4 py-1.5 text-center text-[10px] font-semibold tracking-[0.25em]">
                    {row.divider}
                  </td>
                </tr>
              );
            }
            const [label, value] = row;
            return (
              <tr key={i}>
                <td className="border border-gray-400 bg-gray-50 px-3 sm:px-4 py-2 font-medium text-gray-600 w-[28%] sm:whitespace-nowrap">{label}</td>
                <td className="border border-gray-400 px-3 sm:px-4 py-2 text-gray-800 break-words">{value || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function DataTable({ headers, rows, caption }: { headers: string[]; rows: ReactNode[][]; caption?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        {caption && <caption className="mb-2 text-left text-[11px] text-gray-500">{caption}</caption>}
        <thead>
          <tr>{headers.map(h => <th key={h} className="border border-gray-400 bg-gray-100 px-3 py-2.5 text-center font-semibold text-gray-700">{h}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((cells, i) => (
            <tr key={i} className={i % 2 === 1 ? "bg-slate-50" : ""}>
              {cells.map((cell, j) => <td key={j} className="border border-gray-400 px-3 py-2 text-center break-words">{cell ?? "—"}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function NumberedList({ items }: { items: string[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs">
        <tbody>
          {items.map((item, i) => (
            <tr key={item}>
              <td className="border border-gray-300 bg-gray-50 px-3 py-2 w-8 text-center text-gray-500">{i + 1}</td>
              <td className="border border-gray-300 px-4 py-2 text-gray-800 break-words">{item}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * 실거래 기반 가격의 시점 한계. 실거래는 이미 끝난 거래라 기준일의 거래 가능 가격을 확정하지 못한다.
 * 근거 거래가 언제였고 기준일까지 얼마나 지났는지, 시점 보정을 얼마나 했는지를 가격 바로 아래에 고정해 보여준다.
 */
export function PastTradeNotice({ window, asOf }: { window?: EvidenceWindow | null; asOf?: string }) {
  const adjustment = window?.time_adjustment_pct;
  return (
    <div role="note" aria-label="실거래 근거 시점" className="border border-amber-300 bg-amber-50 px-4 py-3 text-left text-[11px] leading-relaxed text-amber-900">
      {window ? (
        <p className="font-semibold">
          근거 거래 {window.trade_count}건 · {window.first_deal_date} ~ {window.last_deal_date} · 가장 최근 거래는 기준일{asOf ? `(${asOf})` : ""}보다 {window.days_since_last}일 전
          {window.source === "comparables"
            ? ` · 시점 보정 ${adjustment == null ? "없음" : `평균 ${adjustment > 0 ? "+" : ""}${adjustment.toFixed(2)}%`}`
            : " · 모델이 시점·층·면적 차이를 보정"}
        </p>
      ) : <p className="font-semibold">근거 거래 기간을 확인하지 못한 이전 분석입니다.</p>}
      <p className="mt-1">실거래는 과거 거래이며 신고 지연(최대 30일)과 시장 변동 때문에 현재 거래 가능 가격과 다를 수 있습니다. 현재 매물 호가를 함께 확인하세요.</p>
    </div>
  );
}

/** 표시할 절만 골라 "제 n 절" 번호를 순서대로 붙인다. 빈 절을 건너뛰어도 번호가 비지 않게 하기 위함이다. */
export function Sections({ items }: { items: ({ title: string; body: ReactNode } | null | false | undefined)[] }) {
  const visible = items.filter((item): item is { title: string; body: ReactNode } => Boolean(item));
  return <>{visible.map((item, i) => (
    <section key={item.title}>
      <SectionTitle number={`제 ${i + 1} 절`} title={item.title} />
      {item.body}
    </section>
  ))}</>;
}

export function ReportShell({ appraisalDate, query, dataSource, children, before, retryHref = "/appraisal", label = "부동산 AI 시세추정 리포트" }: {
  appraisalDate: string; query?: string; dataSource?: string[]; children: ReactNode; before?: ReactNode; retryHref?: string; label?: string;
}) {
  const today = new Date().toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric" });
  return (
    <div className="report-wrapper min-h-screen bg-slate-300 py-6 px-2 sm:px-4">
      {before}
      <div className="no-print max-w-[880px] mx-auto mb-4 flex justify-between items-center">
        <Link href={retryHref} className="text-sm text-primary-strong hover:underline font-medium">← 새 시세추정</Link>
        <button onClick={() => window.print()} className="px-4 py-2 bg-gray-800 text-white text-sm rounded hover:bg-gray-900 transition-colors">인쇄 / PDF 저장</button>
      </div>
      <div id="appraisal-doc" aria-label={label} className="max-w-[880px] mx-auto bg-white shadow-2xl" style={{ fontFamily: "'Malgun Gothic', 'Apple SD Gothic Neo', '맑은 고딕', sans-serif" }}>
        <div className="border-b-4 border-double border-gray-800 px-5 sm:px-14 pt-10 sm:pt-12 pb-8 text-center">
          <p className="text-[10px] tracking-[0.5em] text-gray-400 mb-2 uppercase">AI Automated Valuation Report</p>
          <h1 className="text-[22px] sm:text-[28px] font-bold tracking-[0.15em] text-gray-900 mb-2">{label}</h1>
          <p className="text-[11px] text-gray-400 mb-5">
            본 리포트는 자동가치산정(AVM) 기반 시세 추정 자료이며, 「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가서가 아닙니다.
          </p>
          <div className="inline-flex flex-wrap justify-center gap-x-10 gap-y-1 border border-gray-300 bg-gray-50 px-5 sm:px-8 py-3 text-xs text-gray-600">
            <div className="flex gap-2"><span className="text-gray-400">기 준 시 점</span><span className="font-semibold text-gray-800">{appraisalDate}</span></div>
            <div className="flex gap-2"><span className="text-gray-400">발 행 일 자</span><span className="font-semibold text-gray-800">{today}</span></div>
          </div>
          {query && <p className="mt-4 text-xs text-gray-400 break-words">조회 내용: {query}</p>}
        </div>
        <div className="px-5 sm:px-14 py-10 space-y-9">
          {children}
          <div className="border-t-2 border-gray-800 pt-6 mt-4">
            <div className="text-[10px] text-gray-400 leading-[1.8]">
              <p className="font-semibold text-gray-500 mb-1.5">【 고 지 사 항 】</p>
              <p>
                1. 본 리포트는 공개 데이터 기반 자동가치산정 모형(AVM, Automated Valuation Model)이
                산출한 <span className="font-semibold text-gray-500">참고용 시세 추정 자료</span>이며,
                「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아니고 법적 효력이 없습니다.
              </p>
              <p>2. 담보 설정·소송·과세 등 법적 효력이 필요한 가치 판단은 국가자격을 보유한 감정평가사에게 의뢰하시기 바랍니다.</p>
              <p>3. 추정 시세는 데이터 상황에 따라 실제 거래 가능 가격과 차이가 있을 수 있으며, 본 리포트를 근거로 한 의사결정의 책임은 이용자에게 있습니다.</p>
              {dataSource && dataSource.length > 0 && <p className="mt-2">데이터 출처: {dataSource.join(" · ")}</p>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
