"use client";
import { useState, type ReactNode } from "react";
import { Trash2 } from "lucide-react";

/**
 * 되돌릴 수 없는 삭제를 한 번 더 확인한다.
 * window.confirm은 화면 흐름을 막고 자동 브라우저 검증도 멈추게 하므로 같은 자리에서 확인·취소를 보여준다.
 * 실패하면 onError로 알려 화면이 조용히 그대로 남지 않게 한다.
 */
export default function ConfirmDeleteButton({ label, message, onConfirm, onError, disabled, title, children }: {
  label: string;
  message: string;
  onConfirm: () => Promise<void>;
  onError: (message: string) => void;
  disabled?: boolean;
  title?: string;
  children?: ReactNode;
}) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  if (!asking) return <button type="button" disabled={disabled} title={title ?? label} aria-label={label}
    onClick={event => { event.stopPropagation(); setAsking(true); }}
    className="text-slate-400 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-40">{children ?? <Trash2 size={16} />}</button>;
  return <span role="group" aria-label={`${label} 확인`} className="inline-flex flex-wrap items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-800"
    onClick={event => event.stopPropagation()}>
    <span>{message}</span>
    <button type="button" disabled={busy} className="rounded bg-red-600 px-2 py-1 font-semibold text-white disabled:opacity-50" onClick={async () => {
      setBusy(true);
      try { await onConfirm(); setAsking(false); }
      catch (reason) { onError(reason instanceof Error && reason.message ? reason.message : `${label}에 실패했습니다. 잠시 후 다시 시도해주세요.`); }
      finally { setBusy(false); }
    }}>{busy ? "삭제 중…" : "삭제"}</button>
    <button type="button" disabled={busy} className="rounded border border-red-200 bg-white px-2 py-1" onClick={() => setAsking(false)}>취소</button>
  </span>;
}
