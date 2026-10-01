"use client";
import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import AppraisalReport from "@/components/AppraisalReport";

/**
 * /report/[id] — history DB에 저장된 시세추정 리포트 재열람.
 * 새로고침·공유·이력에서 다시 열기 모두 지원.
 */
export default function SavedReportPage() {
  const { id } = useParams<{ id: string }>();
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!id) return;
    api.historyOne(Number(id))
      .then(res => setResult(res as Record<string, unknown>))
      .catch(e => setError(e instanceof Error ? e.message : "리포트를 불러올 수 없습니다."))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto text-center py-20 text-slate-400 text-sm">
        리포트를 불러오는 중...
      </div>
    );
  }

  if (error || !result) {
    return (
      <div className="max-w-2xl mx-auto">
        <div className="bg-red-50 border border-red-200 rounded-xl p-5">
          <h2 className="font-semibold text-red-700 mb-2">리포트를 불러올 수 없습니다</h2>
          <p className="text-sm text-red-600">{error || "저장된 결과가 없습니다."}</p>
        </div>
        <Link href="/dashboard" className="mt-4 inline-block text-sm text-primary hover:underline">
          ← 이력 대시보드
        </Link>
      </div>
    );
  }

  return <AppraisalReport result={result} query={(result.query as string) || ""} />;
}
