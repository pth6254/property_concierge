"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Loader2, PlayCircle } from "lucide-react";
import { api } from "@/lib/api";
import { candidateRightsSeed } from "@/lib/candidateRightsSeed";
import { removeSessionValue, setSessionValue, useSessionValue } from "@/lib/sessionStore";
import type { CandidateQuickReview as QuickReview, CaseProperty } from "@/lib/types";

const FUNDING_FIELDS: Record<string, string> = {
  cash_available: "보유 현금", loan_ratio: "대출 비율", owned_homes: "취득 후 주택 수", adjusted_area: "조정대상지역 여부",
  annual_interest_rate: "대출 금리", loan_years: "대출 기간", repayment_type: "상환 방식",
  existing_loan_annual_payment: "기존 대출 연간 상환액", asking_price: "희망가", property_type: "물건 종류",
  buyer_profile: "공통 매수 조건 형식",
};
const APPRAISAL_FIELDS: Record<string, string> = {
  address: "주소", area_sqm: "면적", area_basis: "면적 기준(전용·공급)", exclusive_area_sqm: "전용면적(지금은 공급면적으로 저장됨)",
  property_type: "물건 종류", income_valuation: "임대료·운영비(상가·사무실)",
};
// 이 값들이 빠졌으면 케이스의 공통 매수 조건에서 채운다. 희망가·물건 종류는 후보에서 고친다.
const PROFILE_FIELDS = new Set(["cash_available", "loan_ratio", "owned_homes", "adjusted_area", "annual_interest_rate",
  "loan_years", "repayment_type", "existing_loan_annual_payment", "buyer_profile"]);
const POLL_INTERVAL_MS = 2000;
const POLL_TIMEOUT_MS = 5 * 60 * 1000;

const won = (value: number | null | undefined) => value == null ? "미확인" : `${Math.round(value / 10_000).toLocaleString()}만원`;
const labels = (fields: string[], names: Record<string, string>) => fields.map(field => names[field] ?? field).join(", ");

function sleep(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("aborted", "AbortError")); }, { once: true });
  });
}

function detailOf(reason: unknown, fallback: string): string {
  if (!(reason instanceof Error) || !reason.message) return fallback;
  try {
    const detail = (JSON.parse(reason.message) as { detail?: unknown }).detail;
    return typeof detail === "string" && detail ? detail : fallback;
  } catch {
    return fallback;
  }
}

type JobOutcome = { ok: true; historyId?: number } | { ok: false; message: string };

/**
 * 후보 한 번에 검토. 공통 매수 조건으로 자금을 계산·저장하고 시세추정 작업을 접수한다(서버: candidate_quick_review.py).
 * 이미 유효한 분석은 다시 실행하지 않으며, 권리 점검은 등기부 PDF가 필요해 이동만 안내한다.
 * 시세추정은 별도 실행기에서 진행되므로 화면을 떠나도 후보에 연결된다. 같은 탭에서 돌아오면 진행 상태를 다시 조회한다.
 */
export default function CandidateQuickReview({ property, caseId, reload }: {
  property: CaseProperty; caseId: number; reload: () => Promise<void>;
}) {
  const jobKey = `quickReviewJob:${caseId}:${property.id}`;
  const pendingJob = useSessionValue(jobKey);
  const [result, setResult] = useState<QuickReview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [step, setStep] = useState("");
  const [outcome, setOutcome] = useState<JobOutcome | null>(null);
  // 케이스 화면은 렌더링마다 새 reload 함수를 넘긴다. 의존성에 넣으면 진행 조회가 매번 다시 시작되므로 최신 값만 참조한다.
  const reloadRef = useRef(reload);
  useEffect(() => { reloadRef.current = reload; }, [reload]);

  useEffect(() => {
    if (typeof pendingJob !== "string") return;
    const controller = new AbortController();
    const finish = async (value: JobOutcome) => {
      removeSessionValue(jobKey);
      setOutcome(value);
      await reloadRef.current().catch(() => undefined);
    };
    (async () => {
      const deadline = Date.now() + POLL_TIMEOUT_MS;
      try {
        while (Date.now() < deadline) {
          await sleep(POLL_INTERVAL_MS, controller.signal);
          const job = await api.appraisalJob(pendingJob, controller.signal);
          if (job.step) setStep(job.step);
          if (job.status === "done") return await finish({ ok: true, historyId: job.history_id });
          // 서버가 내부 문구를 사용자 안내로 바꿔 준다(api/user_errors.py). 이미 '시세추정'으로 시작하는 안내에는 맥락을 다시 붙이지 않는다.
          if (job.status === "error") return await finish({ ok: false, message: !job.error ? "시세추정을 완료하지 못했습니다."
            : job.error.startsWith("시세추정") ? job.error : `시세추정을 완료하지 못했습니다: ${job.error}` });
        }
        await finish({ ok: false, message: "시세추정이 예상보다 오래 걸립니다. 완료되면 이 후보에 결과가 표시됩니다." });
      } catch (reason) {
        if (controller.signal.aborted) return;
        await finish({ ok: false, message: detailOf(reason, "진행 상태를 확인하지 못했습니다. 완료되면 이 후보에 결과가 표시됩니다.") });
      }
    })();
    return () => controller.abort();
  }, [pendingJob, jobKey]);

  const run = async () => {
    setBusy(true); setError(""); setOutcome(null); setStep("");
    try {
      const value = await api.candidateQuickReview(caseId, property.id);
      setResult(value);
      if (value.appraisal.status === "queued" && value.appraisal.job_id) setSessionValue(jobKey, value.appraisal.job_id);
      // 자금 결과는 이미 저장됐으므로 아래 분석 카드·다음 행동을 바로 갱신한다.
      await reload();
    } catch (reason) {
      setError(detailOf(reason, "한 번에 검토를 실행하지 못했습니다. 잠시 후 다시 시도해주세요."));
    } finally {
      setBusy(false);
    }
  };

  const running = typeof pendingJob === "string";
  const funding = result?.funding;
  const appraisal = result?.appraisal;
  const appraisalHref = `/appraisal?caseId=${caseId}&candidateId=${property.id}`;

  return <section aria-label={`${property.name} 한 번에 검토`} className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50/40 p-4">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="min-w-0 flex-1">
        <h4 className="text-sm font-semibold">시세·자금 한 번에 검토</h4>
        <p className="mt-1 text-xs text-slate-600">공통 매수 조건으로 자금을 계산하고 시세추정을 시작합니다. 이미 유효한 분석은 다시 실행하지 않으며, 권리 점검은 등기부등본 PDF가 필요합니다.</p>
      </div>
      <button type="button" onClick={() => void run()} disabled={busy || running}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-strong disabled:opacity-50">
        {busy || running ? <Loader2 size={14} className="animate-spin" /> : <PlayCircle size={14} />}
        {busy ? "실행 중…" : running ? "시세추정 진행 중" : "한 번에 검토"}
      </button>
    </div>
    {error && <p role="alert" className="mt-3 text-xs text-red-700">{error}</p>}

    {(result || running || outcome) && <ul className="mt-3 space-y-2 text-xs" aria-live="polite">
      {funding && <li className="rounded border bg-white p-2.5">
        <strong>자금</strong>{" · "}
        {funding.status === "calculated" ? <>
          {funding.input_source === "saved" ? "후보에 저장된 개별 조건으로 현재 희망가에 맞춰 다시 계산해 저장했습니다." : "공통 매수 조건으로 계산해 저장했습니다."}
          <span className="mt-1 block text-slate-700">필요 현금 {won(funding.summary?.required_cash)} · 부족 자금 {won(funding.summary?.cash_shortfall)} · 첫 달 상환액 {won(funding.summary?.monthly_payment)}</span>
          {funding.warnings.length > 0 && <span className="mt-1 block text-amber-800">확인할 사항: {funding.warnings.join(" · ")}</span>}
        </> : funding.status === "current" ? "유효한 자금 분석이 있어 그대로 두었습니다. 조건을 바꾸려면 자금 분석에서 다시 계산하세요."
          : funding.status === "needs_input" ? <>
            <span className="text-amber-800">계산하지 않았습니다. 필요한 조건: {labels(funding.missing, FUNDING_FIELDS)}</span>
            {funding.missing.some(field => PROFILE_FIELDS.has(field)) && <a href="#buyer-profile" className="ml-2 font-semibold text-primary underline">공통 매수 조건 입력</a>}
          </> : <span className="text-red-700">{funding.message || "자금 계산을 완료하지 못했습니다."}</span>}
      </li>}

      {(appraisal || running || outcome) && <li className="rounded border bg-white p-2.5">
        <strong>시세</strong>{" · "}
        {running ? <span>시세추정 진행 중{step ? ` · ${step}` : ""}. 화면을 떠나도 완료되면 후보에 연결됩니다.</span>
          : outcome ? outcome.ok ? <>
            시세추정을 마치고 후보에 연결했습니다. 보류·참고 결과일 수 있으니 아래 시세 분석에서 근거를 확인하세요.
            {outcome.historyId != null && <Link href={`/report/${outcome.historyId}?caseId=${caseId}&candidateId=${property.id}`} className="ml-2 font-semibold text-primary underline">리포트 보기</Link>}
          </> : <><span className="text-red-700">{outcome.message}</span><Link href={appraisalHref} className="ml-2 font-semibold text-primary underline">시세추정 화면</Link></>
          : appraisal?.status === "current" ? appraisal.message || "유효한 시세 분석이 있어 다시 실행하지 않았습니다."
          : appraisal?.status === "needs_input" ? <>
            <span className="text-amber-800">시작하지 않았습니다. 필요한 정보: {labels(appraisal.missing, APPRAISAL_FIELDS)}</span>
            <Link href={appraisal.input_url || appraisalHref} className="ml-2 font-semibold text-primary underline">시세추정 화면에서 입력</Link>
          </> : appraisal?.status === "error" ? <><span className="text-red-700">{appraisal.message || "시세추정을 시작하지 못했습니다."}</span>
            <Link href={appraisalHref} className="ml-2 font-semibold text-primary underline">시세추정 화면</Link></>
          : null}
      </li>}

      {result && <li className="rounded border bg-white p-2.5">
        <strong>권리</strong>{" · "}
        {result.rights.status === "current" ? "권리 점검 결과가 있습니다. 문서 발급일과 판독 상태는 아래 권리 분석에서 확인하세요."
          : <>
            <span className="text-amber-800">{result.rights.status === "stale" ? "확인된 권리 점검 결과가 없습니다(갱신 필요·판독 실패 등). 문서를 다시 올려 확인해주세요." : "등기부등본 PDF를 올려야 점검할 수 있습니다."}</span>
            <Link href="/rights" onClick={() => setSessionValue("rightsCandidate", JSON.stringify(candidateRightsSeed(property, caseId)))} className="ml-2 font-semibold text-primary underline">권리 점검으로 이동</Link>
          </>}
      </li>}
    </ul>}
    {result && <p className="mt-2 text-[11px] text-slate-500">참고용 계산·추정이며 대출 승인이나 감정평가가 아닙니다. 매수 결정은 직접 내려주세요.</p>}
  </section>;
}
