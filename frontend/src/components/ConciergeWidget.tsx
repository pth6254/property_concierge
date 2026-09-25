"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { Bot, Database, MapPin, MessageCircle, Send, Sparkles, X } from "lucide-react";
import { api, ConversationJobError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { CaseProperty, ConciergeRegionItem, ConciergeResponse, PurchaseCase } from "@/lib/types";
import Link from "next/link";
import LawSources from "./LawSources";
import ConciergeComplexCard, { type ComplexCandidateInput } from "./ConciergeComplexCard";
import { useSessionValue, setSessionValue, removeSessionValue } from "@/lib/sessionStore";

type Message = {
  role: "user" | "assistant";
  content: string;
  response?: ConciergeResponse;
};

const HIDDEN_PATHS = [
  "/login", "/register", "/forgot-password", "/reset-password", "/privacy", "/terms",
];

const SUGGESTIONS = [
  "이 후보 시세를 추정해줘",
  "이 후보 자금 분석해줘",
  "후보 비교해줘",
  "서울에서 10억 이하 아파트 동네 추천해줘",
  "실거주할 동네를 찾고 있어",
  "어떤 부동산 기능을 도와줄 수 있어?",
];

const formatPrice = (manwon: number) => manwon >= 10_000
  ? `${(manwon / 10_000).toFixed(manwon % 10_000 ? 1 : 0)}억원`
  : `${manwon.toLocaleString()}만원`;

const formatYm = (ym: string) => ym.length === 6 ? `${ym.slice(0, 4)}.${ym.slice(4)}` : ym;

function FundingConditions({ response }: { response: ConciergeResponse }) {
  const values = response.data.funding_inputs;
  if (!values) return null;
  const lines = [
    values.cash_available != null ? `보유 현금 ${values.cash_available.toLocaleString()}원` : null,
    values.loan_ratio != null ? `대출 ${values.loan_ratio * 100}%` : null,
    values.annual_interest_rate != null ? `연 금리 ${values.annual_interest_rate}%` : null,
    values.loan_years != null ? `${values.loan_years}년` : null,
    values.repayment_type ? { equal_payment: "원리금균등", equal_principal: "원금균등", interest_only: "만기일시" }[values.repayment_type] : null,
    values.owned_homes != null ? `취득 후 ${values.owned_homes}주택` : null,
    values.adjusted_area != null ? (values.adjusted_area ? "조정대상지역" : "비조정지역") : null,
    values.annual_income != null ? `연소득 ${values.annual_income.toLocaleString()}원` : null,
    values.existing_loan_annual_payment != null ? `기존 대출 연 상환 ${values.existing_loan_annual_payment.toLocaleString()}원` : null,
    values.monthly_payment_limit != null ? `월 한도 ${values.monthly_payment_limit.toLocaleString()}원` : null,
  ].filter(Boolean);
  return lines.length > 0 ? <p className="mt-2 rounded-lg bg-slate-50 p-2 text-xs text-slate-600">반영한 조건: {lines.join(" · ")}</p> : null;
}

function CriteriaChips({ response }: { response: ConciergeResponse }) {
  const criteria = response.criteria;
  const chips = [
    criteria.region_name,
    criteria.property_type === "apartment" ? "아파트" : criteria.property_type,
    criteria.budget_max_won ? `${(criteria.budget_max_won / 100_000_000).toLocaleString()}억원 이하` : null,
    criteria.area_min_sqm ? `${criteria.area_min_sqm}㎡ 이상` : null,
  ].filter((value): value is string => Boolean(value));
  if (!chips.length) return null;
  return <div className="mt-2 flex flex-wrap gap-1.5">{chips.map((chip) => (
    <span key={chip} className="rounded-full bg-emerald-50 px-2 py-1 text-[11px] font-medium text-emerald-700">{chip}</span>
  ))}</div>;
}

function RegionCards({ response, saved, onSave }: {
  response: ConciergeResponse;
  saved: Set<string>;
  onSave: (response: ConciergeResponse, item: ConciergeRegionItem) => void;
}) {
  const items = response.data.items ?? [];
  if (!items.length) return null;
  return (
    <div className="mt-3 space-y-2">
      {items.slice(0, 5).map((item) => {
        const budgetFit = item.deal_count
          ? Math.round(item.budget_fit_count / item.deal_count * 100)
          : 0;
        return (
          <article key={item.region_code} className="rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-1.5 text-sm font-bold text-slate-800">
                  <MapPin size={13} className="text-primary" />{item.region_name}
                </div>
                <p className="mt-1 text-[11px] text-slate-500">
                  거래 {item.deal_count.toLocaleString()}건 · 대상 {item.asset_count.toLocaleString()}개
                </p>
              </div>
              <div className="shrink-0 text-right">
                <strong className="text-sm text-primary">{formatPrice(item.avg_price)}</strong>
                <p className="text-[10px] text-slate-400">평균 실거래가</p>
              </div>
            </div>
            <div className="mt-2 flex justify-between border-t border-slate-100 pt-2 text-[11px] text-slate-500">
              <span>{formatPrice(item.price_q1)}~{formatPrice(item.price_q3)}</span>
              {response.criteria.budget_max_won && <span className="font-semibold text-emerald-700">예산 내 {budgetFit}%</span>}
            </div>
            <div className="mt-2 flex items-center justify-between text-[11px]"><span className="text-slate-400">중앙 {formatPrice(item.median_price)} · 신뢰도 {{ high: "높음", medium: "보통", low: "낮음" }[item.confidence]}</span><button type="button" disabled={saved.has(item.region_code)} onClick={() => onSave(response, item)} className="rounded-lg border border-emerald-200 px-2 py-1 font-semibold text-primary hover:bg-emerald-50 disabled:bg-emerald-50">{saved.has(item.region_code) ? "저장됨" : "케이스 저장"}</button></div>
          </article>
        );
      })}
      {response.data.period && (
        <p className="flex items-center gap-1 text-[10px] text-slate-400">
          <Database size={11} />국토교통부 실거래가 · {formatYm(response.data.period.from)}~{formatYm(response.data.period.to)}
        </p>
      )}
    </div>
  );
}

function AppraisalProgress({ jobId, caseId }: { jobId: string; caseId?: number }) {
  const [status, setStatus] = useState("시세추정 진행 중");
  const [historyId, setHistoryId] = useState<number | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const deadline = Date.now() + 5 * 60 * 1000;
    const poll = async () => {
      try {
        const job = await api.appraisalJob(jobId, controller.signal);
        if (controller.signal.aborted) return;
        if (job.status === "done") {
          setHistoryId(job.history_id ?? null);
          setStatus(job.history_id ? "분석 결과를 후보에 저장했습니다." : "분석은 끝났지만 저장 결과를 확인하지 못했습니다.");
          return;
        }
        if (job.status === "error") { setStatus(job.error || "시세추정에 실패했습니다."); return; }
        if (Date.now() >= deadline) { setStatus("분석이 오래 걸리고 있습니다. 잠시 후 후보 또는 이력에서 결과를 확인해주세요."); return; }
        setStatus(job.step ? `진행 중: ${job.step}` : "시세추정 대기 중");
        timer = setTimeout(poll, 2000);
      } catch { if (!controller.signal.aborted) setStatus("진행 상태를 확인하지 못했습니다. 후보와 이력에서 확인해주세요."); }
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [jobId]);
  return <div className="mt-3 rounded-lg border border-emerald-100 p-3 text-xs"><p role="status">{status}</p>{historyId && <Link href={`/report/${historyId}`} className="mr-3 text-primary underline">시세추정 리포트</Link>}{caseId && <Link href={`/cases/${caseId}`} className="text-primary underline">후보 확인</Link>}</div>;
}

export default function ConciergeWidget() {
  const { user, loading } = useAuth();
  if (loading || !user) return null;
  // 계정이 바뀌면 이전 사용자의 화면 상태와 진행 중 복원 요청을 함께 폐기한다.
  return <UserConciergeWidget key={user.id} userId={user.id} />;
}

function UserConciergeWidget({ userId }: { userId: number }) {
  const path = usePathname();
  const { user, loading: authLoading } = useAuth();
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [cases, setCases] = useState<PurchaseCase[]>([]);
  const [caseId, setCaseId] = useState("");
  const [candidates, setCandidates] = useState<CaseProperty[]>([]);
  const [candidateId, setCandidateId] = useState("");
  const [savedRegions, setSavedRegions] = useState<Set<string>>(new Set());
  const [savingComplex, setSavingComplex] = useState(false);
  const saveLock = useRef(false);
  const [candidateNotice, setCandidateNotice] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const storageKey = `concierge-conversation:${userId}`;
  const savedConversationId = useSessionValue(storageKey);
  const [restoreError, setRestoreError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const restoring = savedConversationId === undefined || Boolean(savedConversationId && savedConversationId !== conversationId);

  useEffect(() => {
    if (!savedConversationId || savedConversationId === conversationId) return;
    const controller = new AbortController();
    const restore = async () => {
      try {
        const restored = await api.conciergeConversation(savedConversationId, controller.signal);
        if (controller.signal.aborted) return;
        if (!restored) {
          removeSessionValue(storageKey);
          setRestoreError("이전 대화가 만료되었거나 후보가 삭제되어 새 대화를 시작합니다.");
          return;
        }
        const selectedCase = restored.candidate_context.case_id;
        const detail = selectedCase ? await api.caseOne(selectedCase) : null;
        if (controller.signal.aborted) return;
        setMessages(restored.messages);
        setCaseId(String(selectedCase ?? ""));
        setCandidateId(String(restored.candidate_context.candidate_id ?? ""));
        setCandidates(detail?.properties ?? []);
        setConversationId(restored.conversation_id);
        setRestoreError("");
      } catch {
        if (!controller.signal.aborted) setRestoreError("이전 대화를 불러오지 못했습니다. 다시 시도하거나 새 대화를 시작해주세요.");
      }
    };
    void restore();
    return () => controller.abort();
  }, [savedConversationId, conversationId, storageKey, restoreAttempt]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, []);

  useEffect(() => {
    if (!user || !open) return;
    let cancelled = false;
    api.cases().then((result) => {
      if (cancelled) return;
      setCases(result.items);
      setCaseId((current) => result.items.some((item) => String(item.id) === current) ? current : String(result.items[0]?.id ?? ""));
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [user, open]);

  useEffect(() => {
    let cancelled = false;
    if (!caseId || !open) return;
    api.caseOne(Number(caseId)).then((value) => {
      if (!cancelled) setCandidates(value.properties ?? []);
    }).catch(() => { if (!cancelled) setCandidates([]); });
    return () => { cancelled = true; };
  }, [caseId, open]);

  const saveRegion = async (response: ConciergeResponse, item: ConciergeRegionItem) => {
    try {
      let targetCaseId = caseId;
      if (!targetCaseId) {
        const created = await api.createCase({
          title: `${item.region_name} 매수 검토`,
          budget_max: response.criteria.budget_max_won ?? undefined,
        });
        targetCaseId = String(created.id);
        setCases([created]);
        setCaseId(targetCaseId);
      }
      await api.addCaseRegion(Number(targetCaseId), {
        region_code: item.region_code,
        property_type: response.criteria.property_type ?? "all",
        budget_max_won: response.criteria.budget_max_won ?? undefined,
        months: 12,
        source: "concierge",
      });
      setSavedRegions((current) => new Set(current).add(item.region_code));
    } catch {
      setMessages((current) => [...current, {
        role: "assistant", content: "관심 지역을 검토 케이스에 저장하지 못했습니다.",
      }]);
    }
  };

  const saveComplex = async (response: ConciergeResponse, input: ComplexCandidateInput) => {
    if (saveLock.current || sending || restoring) return;
    saveLock.current = true; setSavingComplex(true); setCandidateNotice("");
    try {
      let target = Number(caseId);
      if (!target) {
        const created = await api.createCase({ title: `${response.data.region_name ?? "단지"} 매수 검토`, budget_max: response.criteria.budget_max_won ?? undefined });
        target = created.id; setCases((current) => [...current, created]); setCaseId(String(target));
      }
      const detail = await api.caseOne(target);
      const properties = detail.properties ?? [];
      // 재클릭·복원 후 같은 후보를 다시 저장하지 않도록 서버의 현재 목록과 대조한다.
      const existing = properties.find((candidate) => candidate.name === input.name && candidate.address === input.address && candidate.area_sqm === input.area_sqm && candidate.category === "apartment");
      const candidate = existing ?? await api.addCaseProperty(target, {
        ...input, category: "apartment", source: "recommendation",
        notes: "챗봇 실거래 단지 추천에서 사용자가 주소·면적을 확인하여 저장. 희망가는 사용자 입력값이며 실거래 평균과 구분함.",
      });
      setCandidates(existing ? properties : [...properties, candidate]);
      setCandidateId(String(candidate.id));
      setCandidateNotice(`${candidate.name} 후보를 ${existing ? "기존 목록에서 선택" : "저장하고 선택"}했습니다. 아래에서 AVM 또는 자금 분석을 요청하세요.${existing ? " 기존 후보의 희망가는 변경하지 않았습니다." : ""}`);
    } finally { saveLock.current = false; setSavingComplex(false); }
  };

  const send = async (suggestion?: string) => {
    const message = (suggestion ?? input).trim();
    if (!message || sending || restoring || saveLock.current) return;
    setInput("");
    setMessages((current) => [...current, { role: "user", content: message }]);
    setSending(true);
    try {
      const selected = candidates.find((candidate) => String(candidate.id) === candidateId && candidate.case_id === Number(caseId));
      const response = await api.conciergeMessage(message, conversationId,
        caseId ? { case_id: Number(caseId), candidate_id: selected?.id } : { clear_context: true });
      setConversationId(response.conversation_id);
      setSessionValue(storageKey, response.conversation_id);
      setMessages((current) => [...current, {
        role: "assistant", content: response.answer, response,
      }]);
    } catch (error: unknown) {
      setMessages((current) => [...current, {
        role: "assistant",
        content: error instanceof ConversationJobError ? error.message : "요청을 처리하지 못했습니다. 로그인 상태와 네트워크 연결을 확인하고 다시 시도해주세요.",
      }]);
    } finally {
      setSending(false);
    }
  };

  if (authLoading || !user || HIDDEN_PATHS.some((hidden) => path.startsWith(hidden))) return null;

  return (
    <div className="no-print">
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-label="AI 컨시어지 열기"
          className="fixed bottom-5 right-4 z-40 flex items-center gap-2 rounded-full bg-brand px-4 py-3 text-sm font-bold text-white shadow-[0_12px_35px_rgba(14,36,30,0.3)] transition hover:-translate-y-0.5 hover:bg-brand-ink md:bottom-6 md:right-6"
        >
          <MessageCircle size={20} /><span>AI 컨시어지</span>
        </button>
      )}

      {open && (
        <>
          <button type="button" aria-label="AI 컨시어지 닫기" onClick={() => setOpen(false)} className="fixed inset-0 z-[65] bg-black/30 md:hidden" />
          <section
            role="dialog"
            aria-modal="true"
            aria-label="AI 부동산 컨시어지"
            className="fixed inset-0 z-[70] flex flex-col overflow-hidden bg-slate-50 shadow-2xl md:inset-auto md:bottom-6 md:right-6 md:h-[min(720px,calc(100vh-48px))] md:w-[430px] md:rounded-2xl md:border md:border-slate-200"
          >
            <header className="flex items-center justify-between bg-brand px-4 py-3.5 text-white">
              <div className="flex items-center gap-3">
                <span className="grid h-9 w-9 place-items-center rounded-xl bg-white/10"><Bot size={20} /></span>
                <div><h2 className="text-sm font-bold">AI 부동산 컨시어지</h2><p className="text-[11px] text-white/55">실거래 데이터와 서비스 기능을 연결합니다</p></div>
              </div>
              <button type="button" onClick={() => setOpen(false)} aria-label="닫기" className="rounded-lg p-2 text-white/70 hover:bg-white/10 hover:text-white"><X size={19} /></button>
            </header>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {restoring && !restoreError && <p role="status" className="text-sm text-slate-500">이전 대화를 불러오고 있습니다…</p>}
              {restoreError && <div role="status" className="text-sm text-slate-600">{restoreError}{restoring && <button type="button" onClick={() => { setRestoreError(""); setRestoreAttempt((value) => value + 1); }} className="ml-2 underline">다시 시도</button>}</div>}
              {messages.length === 0 && (
                <div className="pt-4 text-center">
                  <span className="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-emerald-50 text-primary"><Sparkles size={22} /></span>
                  <h3 className="mt-3 text-base font-bold text-slate-800">어떤 부동산을 찾고 계세요?</h3>
                  <p className="mx-auto mt-1 max-w-[310px] text-xs leading-5 text-slate-500">동네 추천·후보 시세추정·자금 분석·후보 비교를 지원합니다. 후보를 선택하고 요청하세요. 같은 후보의 금융 조건은 이어서 사용할 수 있습니다.</p>
                  <div className="mt-5 space-y-2 text-left">{SUGGESTIONS.map((suggestion) => (
                    <button key={suggestion} type="button" onClick={() => send(suggestion)} className="w-full rounded-xl border border-slate-200 bg-white px-3.5 py-3 text-left text-xs text-slate-600 shadow-sm hover:border-emerald-300 hover:text-primary">{suggestion}</button>
                  ))}</div>
                </div>
              )}

              {messages.map((message, index) => (
                <div key={`${message.role}-${index}`} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`max-w-[90%] rounded-2xl px-3.5 py-3 text-sm leading-6 ${message.role === "user" ? "rounded-br-md bg-primary text-white" : "rounded-bl-md bg-white text-slate-700 shadow-sm"}`}>
                    <p className="whitespace-pre-wrap">{message.content}</p>
                    <LawSources sources={message.response?.data.sources} />
                    {message.response?.data.disclaimer && <p className="mt-2 text-xs text-amber-700">{message.response.data.disclaimer}</p>}
                    {message.response && <CriteriaChips response={message.response} />}
                    {message.response && <FundingConditions response={message.response} />}
                    {message.response && <RegionCards response={message.response} saved={savedRegions} onSave={saveRegion} />}
                    {message.response?.tool_used === "select_properties" && message.response.data.results?.map((item) => {
                      const response = message.response!;
                      return <ConciergeComplexCard key={`${item.dong}-${item.complex_name}`} item={item} caseId={caseId} region={response.data.region_name ?? response.criteria.region_name ?? ""} disabled={sending || restoring || savingComplex} onSave={(input) => saveComplex(response, input)} />;
                    })}
                    {message.response?.data.job_id && <AppraisalProgress jobId={message.response.data.job_id} caseId={message.response.data.case_id} />}
                    {message.response?.data.input_url && <Link href={message.response.data.input_url} className="text-primary underline">후보 정보 확인하고 시세추정</Link>}
                    {message.response?.data.result_url && <Link href={message.response.data.result_url} className="mt-2 block text-primary underline">{message.response.tool_used === "search_listings" ? "매물 보관함에서 확인" : "케이스에서 분석·비교 결과 확인"}</Link>}
                  </div>
                </div>
              ))}
              {sending && <div className="flex justify-start"><div className="rounded-2xl rounded-bl-md bg-white px-4 py-3 text-xs text-slate-400 shadow-sm"><span className="animate-pulse">데이터를 확인하고 있어요…</span></div></div>}
              <div ref={bottomRef} />
            </div>

            <footer className="border-t border-slate-200 bg-white p-3">
              {candidateNotice && <p role="status" className="mb-2 text-xs text-emerald-700">{candidateNotice}</p>}
              {candidateId && <div className="mb-2 flex gap-2 text-xs"><button type="button" disabled={sending || restoring || savingComplex} onClick={() => send("AVM 실행해줘")} className="rounded border px-2 py-1 text-primary">선택 후보 AVM 실행</button><button type="button" disabled={sending || restoring || savingComplex} onClick={() => send("이 후보 자금 분석해줘")} className="rounded border px-2 py-1 text-primary">선택 후보 자금 분석</button></div>}
              <label className="mb-2 block text-xs text-slate-500">분석할 후보<select aria-label="분석할 후보" disabled={sending || savingComplex} value={candidateId} onChange={(event) => setCandidateId(event.target.value)} className="ml-2 rounded border p-1"><option value="">후보 선택</option>{candidates.filter((candidate) => candidate.case_id === Number(caseId)).map((candidate) => <option key={candidate.id} value={candidate.id}>{candidate.name}</option>)}</select></label>
              {cases.length > 0 && <div className="mb-2 flex items-center gap-2 px-1"><label className="shrink-0 text-[11px] text-slate-500">검토 케이스</label><select aria-label="검토 케이스" disabled={sending || savingComplex} value={caseId} onChange={(event) => { setCaseId(event.target.value); setCandidateId(""); }} className="min-w-0 flex-1 rounded border border-slate-200 bg-slate-50 px-2 py-1 text-[11px]">{cases.map((item) => <option key={item.id} value={item.id}>{item.title}</option>)}</select></div>}
              <button type="button" disabled={sending || savingComplex} onClick={() => { removeSessionValue(storageKey); setMessages([]); setConversationId(null); setRestoreError(""); }} className="mb-2 text-xs text-slate-500 underline">새 대화 시작 · 기억한 조건 초기화</button>
              <div className="flex items-end gap-2 rounded-xl border border-slate-300 bg-white p-1.5 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/10">
                <textarea
                  rows={1}
                  value={input}
                  onChange={(event) => setInput(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                      event.preventDefault(); send();
                    }
                  }}
                  placeholder="예산과 희망 지역을 말씀해 주세요"
                  disabled={sending || restoring}
                  className="max-h-28 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none placeholder:text-slate-400"
                />
                <button type="button" onClick={() => send()} disabled={sending || !input.trim()} aria-label="메시지 보내기" className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-primary text-white hover:bg-primary-strong disabled:opacity-35"><Send size={17} /></button>
              </div>
              <p className="mt-2 text-center text-[10px] text-slate-400">실거래 기반 참고용 정보이며 전문 감정평가·법률·세무 자문이 아닙니다.</p>
            </footer>
          </section>
        </>
      )}
    </div>
  );
}
