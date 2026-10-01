"use client";
import { useMemo } from "react";
import Link from "next/link";
import AppraisalReport from "@/components/AppraisalReport";
import { useSessionValue } from "@/lib/sessionStore";

/**
 * /report — 방금 실행한 시세추정 결과 (sessionStorage)
 * 저장된 리포트 재열람은 /report/[id] 사용.
 */
export default function ReportPage() {
  const rawResult = useSessionValue("appraisalResult");
  const query = useSessionValue("appraisalQuery") ?? "";

  const result = useMemo(
    () => (rawResult ? (JSON.parse(rawResult) as Record<string, unknown>) : null),
    [rawResult],
  );

  // undefined = 아직 클라이언트에서 읽기 전 — "결과 없음" 화면이 한 번
  // 스쳤다 사라지지 않도록 아무것도 그리지 않는다.
  if (rawResult === undefined) return null;

  if (!result) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20">
        <p className="text-slate-500 mb-4">시세추정 결과가 없습니다.</p>
        <Link
          href="/appraisal"
          className="inline-block px-6 py-2.5 bg-primary text-white rounded-lg text-sm font-semibold hover:bg-primary-strong"
        >
          AI 시세추정 시작하기
        </Link>
      </div>
    );
  }

  if (result.error) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-xl p-5">
          <h2 className="font-semibold text-red-700 mb-2">시세추정 실패</h2>
          <p className="text-sm text-red-600">{String(result.error)}</p>
        </div>
        <Link href="/appraisal" className="mt-4 inline-block text-sm text-primary hover:underline">
          ← 다시 시도
        </Link>
      </div>
    );
  }

  return <AppraisalReport result={result} query={query} />;
}
