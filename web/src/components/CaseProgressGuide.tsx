import Link from "next/link";
import { ArrowRight, CheckCircle2 } from "lucide-react";
import type { PurchaseCase } from "@/lib/types";
import { caseSteps, nextCaseStep } from "@/lib/caseProgress";

/**
 * 케이스 화면의 유일한 진행 표시. 이전에는 단계 경로·6단계 안내·체크리스트 진행률이 따로 쌓여 있어
 * 무엇을 해야 하는지가 흐려졌다. 다음 단계 하나를 앞세우고 단계 목록과 체크리스트 수치를 함께 보여준다.
 */
export default function CaseProgressGuide({ item }: { item: PurchaseCase }) {
  const steps = caseSteps(item);
  const next = nextCaseStep(item);
  const workspace = item.workspace;
  return <section aria-label="매수 검토 진행 안내" className="rounded-xl border border-emerald-100 bg-emerald-50 p-4">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h2 className="font-bold">다음 단계: {next.label}</h2>
        <p className="mt-1 text-sm">{next.action}</p>
      </div>
      <Link href={next.href} className="inline-flex shrink-0 items-center gap-1 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-strong">이어서 하기 <ArrowRight size={15} aria-hidden="true" /></Link>
    </div>
    <ol className="mt-3 flex flex-wrap gap-2 text-xs">{steps.map((step, i) => <li key={step.key}>
      <Link href={step.href} aria-current={step.key === next.key ? "step" : undefined}
        className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-1 ${step.key === next.key ? "border-primary bg-white font-semibold text-primary" : step.done ? "border-emerald-200 bg-white text-emerald-700" : "border-slate-200 bg-white/70 text-slate-600"}`}>
        {step.done ? <CheckCircle2 size={12} aria-label="완료" /> : <span aria-hidden="true">{i + 1}.</span>}{step.label}
      </Link>
    </li>)}</ol>
    {workspace && workspace.checklist_total > 0 && <div className="mt-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-600">
        <span>후보 체크리스트 완료 {workspace.checklist_done}/{workspace.checklist_total} ({workspace.progress_percent}%)</span>
        <span><span className="text-amber-700">주의 {workspace.warning_count}</span> · <span className="text-red-700">진행 불가 {workspace.blocked_count}</span></span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-white" role="progressbar" aria-label="후보 체크리스트 진행률" aria-valuemin={0} aria-valuemax={100} aria-valuenow={workspace.progress_percent}>
        <div className="h-full rounded-full bg-primary" style={{ width: `${workspace.progress_percent}%` }} />
      </div>
    </div>}
    <p className="mt-2 text-xs text-slate-600">이 안내는 작업 진행 기준입니다. 분석 완료·후보 선택이 거래 안전이나 대출 승인을 보장하지 않습니다.</p>
  </section>;
}
