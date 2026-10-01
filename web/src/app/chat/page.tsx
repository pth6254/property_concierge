"use client";
import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import LawSources from "@/components/LawSources";
import type { ChatSource } from "@/lib/types";
import { useAuth } from "@/lib/auth";
import { useSessionValue, setSessionValue, removeSessionValue } from "@/lib/sessionStore";

type Msg = {
  role: "user" | "assistant";
  content: string;
  sources?: ChatSource[];
  tool?: string | null;
  disclaimer?: string;
};

const SUGGESTIONS = [
  "전세 보증금을 못 받고 있는데 어떻게 해야 하나요?",
  "성인 자녀에게 5억 증여하면 증여세 얼마인가요?",
  "묵시적 갱신되면 언제 나갈 수 있나요?",
  "1주택 10억에 팔면 양도세 나오나요?",
];

export default function ChatPage() {
  const { user, loading } = useAuth();
  return <ChatConversation key={user?.id ?? "guest"} userId={user?.id} authLoading={loading} />;
}

function ChatConversation({ userId, authLoading }: { userId?: number; authLoading: boolean }) {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const storageKey = `law-chat-conversation:${userId ?? "guest"}`;
  const savedId = useSessionValue(storageKey);
  const [restoreError, setRestoreError] = useState("");
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const restoring = authLoading || Boolean(userId && (savedId === undefined || (savedId && savedId !== conversationId)));

  useEffect(() => {
    if (!userId || !savedId || savedId === conversationId) return;
    const controller = new AbortController();
    const restore = async () => {
      try {
        const result = await api.chatConversation(savedId, controller.signal);
        if (controller.signal.aborted) return;
        if (!result) {
          removeSessionValue(storageKey);
          setRestoreError("이전 대화가 만료되어 새 대화를 시작합니다.");
          return;
        }
        setMessages(result.messages);
        setConversationId(result.conversation_id);
        setRestoreError("");
      } catch {
        if (!controller.signal.aborted) setRestoreError("대화를 불러오지 못했습니다. 다시 시도하거나 새 대화를 시작해주세요.");
      }
    };
    void restore();
    return () => controller.abort();
  }, [userId, savedId, conversationId, storageKey, restoreAttempt]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const send = async (text?: string) => {
    const q = (text ?? input).trim();
    if (!q || loading || restoring) return;
    setInput("");
    const nextMsgs: Msg[] = [...messages, { role: "user", content: q }];
    setMessages(nextMsgs);
    setLoading(true);
    try {
      const history = nextMsgs.slice(0, -1).slice(-6).map(m => ({ role: m.role, content: m.content }));
      const res = await api.chat(q, history, conversationId);
      if (res.conversation_id && userId) {
        setConversationId(res.conversation_id);
        setSessionValue(storageKey, res.conversation_id);
      }
      setMessages([...nextMsgs, {
        role: "assistant", content: res.answer,
        sources: res.sources, tool: res.tool_used, disclaimer: res.disclaimer,
      }]);
    } catch (e: unknown) {
      setMessages([...nextMsgs, {
        role: "assistant",
        content: "죄송합니다. 답변 생성에 실패했습니다. 잠시 후 다시 시도해주세요."
          + (e instanceof Error ? ` (${e.message.slice(0, 80)})` : ""),
      }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-3xl mx-auto flex flex-col h-[calc(100vh-3rem)]">
      <h1 className="text-2xl font-bold mb-1">부동산 법률·세금 AI 안내</h1>
      <div className="mb-2 flex items-center justify-between gap-2 text-xs text-slate-500">
        <span>{userId ? "이 탭에서 최근 20회 대화를 복원합니다 · 마지막 질문 후 24시간 보관" : "로그인하면 새로고침 후 대화를 복원할 수 있습니다"}</span>
        <button type="button" disabled={loading} onClick={() => { removeSessionValue(storageKey); setConversationId(null); setMessages([]); setInput(""); setRestoreError(""); }} className="shrink-0 underline">새 대화 시작</button>
      </div>
      <p className="text-xs text-amber-600 bg-amber-50 border border-amber-200 px-3 py-2 rounded-lg mb-4">
        일반 정보 안내 서비스입니다. 법률·세무 상담이 아니며, 개별 사안은 변호사·세무사와 상담하세요.
      </p>

      {/* 메시지 목록 */}
      <div className="flex-1 overflow-y-auto space-y-4 pb-4">
        {restoring && !restoreError && <p role="status" className="text-sm text-slate-500">이전 대화를 불러오고 있습니다…</p>}
        {restoreError && <p role="status" className="text-sm text-slate-600">{restoreError}{restoring && <button type="button" onClick={() => { setRestoreError(""); setRestoreAttempt(value => value + 1); }} className="ml-2 underline">다시 시도</button>}</p>}
        {messages.length === 0 && (
          <div className="text-center pt-10">
            <p className="text-slate-400 text-sm mb-5">
              임대차·전세사기·세금·상속·증여 관련 질문을 해보세요.<br />
              증여세·상속세·양도세는 세법 기반 계산기가 자동 실행됩니다.
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {SUGGESTIONS.map(s => (
                <button key={s} onClick={() => send(s)}
                  className="text-xs bg-white border border-slate-200 rounded-full px-3 py-1.5 text-slate-600 hover:border-primary hover:text-primary">
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[85%] rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap ${
              m.role === "user" ? "bg-primary text-white" : "bg-white shadow text-slate-800"
            }`}>
              {m.tool && (
                <span className="inline-block text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-full px-2 py-0.5 mb-2">
                  {m.tool} 실행됨
                </span>
              )}
              <div>{m.content}</div>
              <LawSources sources={m.sources} />
              {m.disclaimer && <p className="mt-2 text-xs text-amber-700">{m.disclaimer}</p>}
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-white shadow rounded-2xl px-4 py-3 text-sm text-slate-400 animate-pulse">
              답변 작성 중...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 입력 */}
      <div className="flex gap-2 pt-3 border-t border-slate-200">
        <input
          className="flex-1 border border-slate-300 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
          placeholder="질문을 입력하세요 (예: 전세 계약 전 뭘 확인해야 하나요?)"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && !e.nativeEvent.isComposing && send()}
          disabled={loading || restoring}
        />
        <button onClick={() => send()} disabled={loading || restoring || !input.trim()}
          className="px-5 py-2.5 bg-primary text-white rounded-xl text-sm font-semibold hover:bg-primary-strong disabled:opacity-40">
          전송
        </button>
      </div>
    </div>
  );
}
