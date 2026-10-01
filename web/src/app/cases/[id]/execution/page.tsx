"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import type {
  CaseExecution, CaseExecutionTask, ExecutionActor, ExecutionPhase,
  ExecutionTaskStatus, PurchaseCase,
} from "@/lib/types";

const PHASES: { value: ExecutionPhase; label: string }[] = [
  { value: "before_contract", label: "계약 전" },
  { value: "before_closing", label: "잔금 전" },
  { value: "closing_day", label: "잔금일" },
  { value: "after_closing", label: "거래 후" },
];
const ACTORS: { value: ExecutionActor; label: string }[] = [
  { value: "self", label: "본인" }, { value: "bank", label: "은행" },
  { value: "broker", label: "중개사" }, { value: "legal_agent", label: "법무사" },
  { value: "tax_agent", label: "세무사" }, { value: "other", label: "기타" },
];
const STATUS_LABEL: Record<ExecutionTaskStatus, string> = {
  scheduled: "예정", in_progress: "진행 중", waiting_external: "외부 확인 대기",
  done: "완료", problem: "문제 발견", not_applicable: "해당 없음",
};

type VerificationDraft = {
  task: CaseExecutionTask; status: "done" | "problem";
  checkedBy: string; outcome: string; evidenceNote: string; followUp: string;
};

export default function CaseExecutionPage() {
  const caseId = Number(useParams<{ id: string }>().id);
  const [caseItem, setCaseItem] = useState<PurchaseCase | null>(null);
  const [execution, setExecution] = useState<CaseExecution | null>(null);
  const [contractDate, setContractDate] = useState("");
  const [closingDate, setClosingDate] = useState("");
  const [verification, setVerification] = useState<VerificationDraft | null>(null);
  const [newTask, setNewTask] = useState<{ phase: ExecutionPhase; title: string; actor: ExecutionActor; dueDate: string }>({ phase: "before_contract", title: "", actor: "self", dueDate: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [caseValue, executionValue] = await Promise.all([api.caseOne(caseId), api.caseExecution(caseId)]);
        if (cancelled) return;
        setCaseItem(caseValue); setExecution(executionValue);
        setContractDate(executionValue.plan?.contract_planned_date ?? "");
        setClosingDate(executionValue.plan?.closing_planned_date ?? "");
      } catch { if (!cancelled) setError("실행 계획을 불러오지 못했습니다."); }
      finally { if (!cancelled) setLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [caseId]);

  const refresh = async () => setExecution(await api.caseExecution(caseId));
  const saveSchedule = async () => {
    setSaving(true); setError("");
    try {
      const value = await api.updateCaseExecution(caseId, {
        contract_planned_date: contractDate || null, closing_planned_date: closingDate || null,
      });
      setExecution(value);
    } catch { setError("일정을 저장하지 못했습니다. 계약 예정일이 잔금 예정일보다 늦지 않은지 확인해주세요."); }
    finally { setSaving(false); }
  };
  const changeSimpleStatus = async (task: CaseExecutionTask, status: ExecutionTaskStatus) => {
    if (status === "done" || status === "problem") {
      setVerification({ task, status, checkedBy: task.checked_by, outcome: task.outcome, evidenceNote: task.evidence_note, followUp: task.follow_up });
      return;
    }
    try { await api.updateExecutionTask(caseId, task.id, { status }); await refresh(); }
    catch { setError("할 일 상태를 변경하지 못했습니다."); }
  };
  const saveVerification = async () => {
    if (!verification || !verification.checkedBy.trim() || !verification.outcome.trim()) {
      setError("완료 또는 문제 발견으로 기록하려면 확인자와 확인 결과가 필요합니다."); return;
    }
    setSaving(true); setError("");
    try {
      await api.updateExecutionTask(caseId, verification.task.id, {
        status: verification.status, checked_by: verification.checkedBy.trim(),
        outcome: verification.outcome.trim(), evidence_note: verification.evidenceNote.trim(),
        follow_up: verification.followUp.trim(),
      });
      setVerification(null); await refresh();
    } catch { setError("확인 결과를 저장하지 못했습니다."); }
    finally { setSaving(false); }
  };
  const addTask = async () => {
    if (!newTask.title.trim()) { setError("추가할 할 일의 이름을 입력해주세요."); return; }
    try {
      await api.addExecutionTask(caseId, { phase: newTask.phase, title: newTask.title.trim(), actor_type: newTask.actor, due_date: newTask.dueDate || null });
      setNewTask({ phase: newTask.phase, title: "", actor: "self", dueDate: "" }); await refresh();
    } catch { setError("할 일을 추가하지 못했습니다."); }
  };
  const removeTask = async (taskId: number) => {
    try { await api.deleteExecutionTask(caseId, taskId); await refresh(); }
    catch { setError("직접 추가한 할 일만 삭제할 수 있습니다."); }
  };

  if (loading) return <div className="py-20 text-center text-slate-400">실행 계획을 불러오는 중...</div>;
  if (!caseItem || !execution) return <div className="py-20 text-center text-slate-500">실행 계획을 찾을 수 없습니다.</div>;
  if (execution.requires_selection) return <div className="mx-auto max-w-3xl rounded-2xl border bg-white p-8 text-center shadow-sm"><h1 className="text-xl font-bold">먼저 최종 후보를 선택해주세요</h1><p className="mt-2 text-sm text-slate-500">실행 계획은 선택한 매물을 기준으로 계약·잔금 일정을 관리합니다.</p><Link href={`/cases/${caseId}/comparison`} className="mt-5 inline-block rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white">후보 비교로 이동</Link></div>;

  const selected = caseItem.properties?.find((property) => property.id === execution.plan?.property_id);
  const summary = execution.summary;
  return <div className="mx-auto max-w-6xl space-y-5">
    <header><Link href={`/cases/${caseId}`} className="text-sm font-medium text-primary hover:underline">← 검토 워크스페이스</Link><h1 className="mt-3 text-2xl font-bold">{caseItem.title} 실행 계획</h1><p className="mt-1 text-sm text-slate-500">최종 후보 <strong className="text-slate-700">{selected?.name ?? "선택 매물"}</strong>의 계약부터 소유권 이전까지 확인 기록을 남깁니다.</p></header>
    {error && <p className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">{error}</p>}

    <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
      <div className="rounded-2xl border bg-white p-4 shadow-sm lg:col-span-2"><p className="text-xs text-slate-500">준비도</p><div className="mt-2 flex items-end gap-2"><strong className="text-3xl text-primary">{summary.progress_percent}%</strong><span className="pb-1 text-sm text-slate-500">{summary.done}/{summary.total}개 확인</span></div><div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full bg-primary" style={{ width: `${summary.progress_percent}%` }} /></div></div>
      <SummaryCard label="기한 경과" value={summary.overdue} tone="amber" />
      <SummaryCard label="문제 발견" value={summary.problems} tone="red" />
      <SummaryCard label="외부 대기" value={summary.waiting_external} tone="slate" />
    </section>

    {summary.blockers.length > 0 && <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4"><h2 className="flex items-center gap-2 font-bold text-amber-900"><AlertTriangle size={18} />지금 확인할 항목</h2><ul className="mt-2 space-y-1 text-sm text-amber-800">{summary.blockers.map((item) => <li key={`${item.task_id}-${item.reason}`}>· {item.title} — {item.reason}</li>)}</ul></section>}

    <section className="rounded-2xl border bg-white p-5 shadow-sm"><div className="flex flex-wrap items-end gap-3"><label className="text-sm"><span className="mb-1 block font-medium">계약 예정일</span><input type="date" value={contractDate} onChange={(event) => setContractDate(event.target.value)} className="rounded-lg border px-3 py-2" /></label><label className="text-sm"><span className="mb-1 block font-medium">잔금 예정일</span><input type="date" value={closingDate} onChange={(event) => setClosingDate(event.target.value)} className="rounded-lg border px-3 py-2" /></label><button disabled={saving} onClick={saveSchedule} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">일정 저장</button></div><p className="mt-3 text-xs text-slate-500">할 일 날짜는 법정기한이 아닌 서비스 권장일입니다. 계약 조건과 전문가 안내를 우선 확인하세요.</p></section>

    {PHASES.map((phase) => <section key={phase.value} className="rounded-2xl border bg-white p-5 shadow-sm"><h2 className="font-bold">{phase.label}</h2><div className="mt-3 divide-y">{execution.tasks.filter((task) => task.phase === phase.value).map((task) => <TaskRow key={task.id} task={task} onStatus={changeSimpleStatus} onVerify={(status) => setVerification({ task, status, checkedBy: task.checked_by, outcome: task.outcome, evidenceNote: task.evidence_note, followUp: task.follow_up })} onDelete={removeTask} />)}</div></section>)}

    <section className="rounded-2xl border border-dashed bg-white p-5"><h2 className="flex items-center gap-2 font-bold"><Plus size={18} />내 할 일 추가</h2><div className="mt-3 grid gap-2 md:grid-cols-5"><select value={newTask.phase} onChange={(event) => setNewTask({ ...newTask, phase: event.target.value as ExecutionPhase })} className="rounded-lg border px-3 py-2 text-sm">{PHASES.map((phase) => <option key={phase.value} value={phase.value}>{phase.label}</option>)}</select><input value={newTask.title} onChange={(event) => setNewTask({ ...newTask, title: event.target.value })} placeholder="예: 이삿짐 업체 예약" className="rounded-lg border px-3 py-2 text-sm md:col-span-2" /><select value={newTask.actor} onChange={(event) => setNewTask({ ...newTask, actor: event.target.value as ExecutionActor })} className="rounded-lg border px-3 py-2 text-sm">{ACTORS.map((actor) => <option key={actor.value} value={actor.value}>{actor.label}</option>)}</select><input type="date" value={newTask.dueDate} onChange={(event) => setNewTask({ ...newTask, dueDate: event.target.value })} className="rounded-lg border px-3 py-2 text-sm" /></div><button onClick={addTask} className="mt-3 rounded-lg border border-primary px-4 py-2 text-sm font-semibold text-primary">추가</button></section>

    {verification && <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"><section className="w-full max-w-lg rounded-2xl bg-white p-5 shadow-xl"><h2 className="font-bold">{verification.task.title} 결과 기록</h2><div className="mt-4 grid gap-3"><label className="text-sm"><span className="mb-1 block font-medium">상태</span><select value={verification.status} onChange={(event) => setVerification({ ...verification, status: event.target.value as "done" | "problem" })} className="w-full rounded-lg border px-3 py-2"><option value="done">완료</option><option value="problem">문제 발견</option></select></label><label className="text-sm"><span className="mb-1 block font-medium">확인자 *</span><input value={verification.checkedBy} onChange={(event) => setVerification({ ...verification, checkedBy: event.target.value })} placeholder="예: 본인, OO은행 담당자" className="w-full rounded-lg border px-3 py-2" /></label><label className="text-sm"><span className="mb-1 block font-medium">확인 결과 *</span><textarea value={verification.outcome} onChange={(event) => setVerification({ ...verification, outcome: event.target.value })} rows={3} className="w-full rounded-lg border p-3" /></label><label className="text-sm"><span className="mb-1 block font-medium">근거 메모</span><input value={verification.evidenceNote} onChange={(event) => setVerification({ ...verification, evidenceNote: event.target.value })} placeholder="문서명·통화 일시 등" className="w-full rounded-lg border px-3 py-2" /></label><label className="text-sm"><span className="mb-1 block font-medium">후속 조치</span><input value={verification.followUp} onChange={(event) => setVerification({ ...verification, followUp: event.target.value })} className="w-full rounded-lg border px-3 py-2" /></label></div><div className="mt-4 flex justify-end gap-2"><button onClick={() => setVerification(null)} className="rounded-lg border px-4 py-2 text-sm">취소</button><button disabled={saving} onClick={saveVerification} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">결과 저장</button></div></section></div>}
  </div>;
}

function SummaryCard({ label, value, tone }: { label: string; value: number; tone: "amber" | "red" | "slate" }) {
  const color = tone === "red" ? "text-red-600" : tone === "amber" ? "text-amber-600" : "text-slate-600";
  return <div className="rounded-2xl border bg-white p-4 shadow-sm"><p className="text-xs text-slate-500">{label}</p><strong className={`mt-2 block text-2xl ${color}`}>{value}</strong></div>;
}

function TaskRow({ task, onStatus, onVerify, onDelete }: { task: CaseExecutionTask; onStatus: (task: CaseExecutionTask, status: ExecutionTaskStatus) => void; onVerify: (status: "done" | "problem") => void; onDelete: (id: number) => void }) {
  const actor = ACTORS.find((item) => item.value === task.actor_type)?.label ?? task.actor_type;
  return <div className="grid gap-3 py-4 md:grid-cols-[1fr_auto] md:items-center"><div><div className="flex flex-wrap items-center gap-2"><span className={task.status === "done" ? "text-emerald-600" : task.status === "problem" ? "text-red-600" : "text-slate-400"}>{task.status === "done" ? <CheckCircle2 size={18} /> : task.status === "problem" ? <AlertTriangle size={18} /> : <Clock3 size={18} />}</span><h3 className="font-semibold">{task.title}</h3>{task.required && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-600">필수</span>}{task.overdue && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-700">기한 경과</span>}</div><p className="mt-1 text-xs text-slate-500">담당 {actor} · {task.due_date ?? "일정 미정"}{task.checked_by && ` · ${task.checked_by} 확인`}</p>{task.outcome && <p className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-xs text-slate-700">{task.outcome}</p>}{task.evidence_note && <p className="mt-1 text-xs text-slate-500">근거: {task.evidence_note}</p>}{task.follow_up && <p className="mt-1 text-xs text-amber-700">후속 조치: {task.follow_up}</p>}</div><div className="flex items-center gap-2"><select value={task.status} onChange={(event) => onStatus(task, event.target.value as ExecutionTaskStatus)} className="rounded-lg border px-2 py-1.5 text-xs">{Object.entries(STATUS_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><button onClick={() => onVerify(task.status === "problem" ? "problem" : "done")} className="rounded-lg border px-3 py-1.5 text-xs">결과 기록</button>{task.source === "user" && <button onClick={() => onDelete(task.id)} aria-label={`${task.title} 삭제`} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600"><Trash2 size={16} /></button>}</div></div>;
}
