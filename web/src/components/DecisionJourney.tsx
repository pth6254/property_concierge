import Link from "next/link";
import { ChevronRight } from "lucide-react";

export default function DecisionJourney({ current, caseId }: {
  current: "explore" | "listings" | "cases"; caseId?: string;
}) {
  const steps = [
    { key: "explore", label: "동네 탐색", href: caseId ? `/explore?case_id=${encodeURIComponent(caseId)}` : "/explore" },
    { key: "listings", label: "매물 보관함", href: caseId ? `/listings?case_id=${encodeURIComponent(caseId)}` : "/listings" },
    { key: "cases", label: "후보 검토·비교", href: caseId ? `/cases/${encodeURIComponent(caseId)}` : "/cases" },
  ];
  return <nav aria-label="매수 검토 단계" className="mb-5 grid grid-cols-3 items-center gap-2 text-xs sm:flex sm:flex-wrap sm:text-sm">
    {steps.map((step, index) => <span key={step.key} className="flex min-w-0 items-center gap-2">
      {index > 0 && <ChevronRight size={14} className="hidden text-slate-400 sm:block" aria-hidden="true" />}
      <Link href={step.href} aria-current={current === step.key ? "step" : undefined}
        className={`w-full rounded-full px-2 py-2 text-center font-semibold focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary sm:w-auto sm:px-3 sm:py-1.5 ${current === step.key ? "bg-primary text-white" : "bg-white text-slate-600 hover:bg-emerald-50"}`}>
        {index + 1}. {step.label}
      </Link>
    </span>)}
  </nav>;
}
