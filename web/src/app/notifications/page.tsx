"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Bell, Clock, FileWarning, RefreshCw, TrendingUp, type LucideIcon } from "lucide-react";
import { api } from "@/lib/api";
import { announceNotificationsChanged } from "@/lib/notifications";
import type { NotificationItem, NotificationKind } from "@/lib/types";

const KINDS: Record<NotificationKind, { label: string; icon: LucideIcon; tone: string }> = {
  trade_update: { label: "실거래 갱신", icon: TrendingUp, tone: "bg-sky-50 text-sky-700" },
  analysis_expired: { label: "분석 만료", icon: Clock, tone: "bg-amber-50 text-amber-800" },
  listing_reconfirm: { label: "매물 재확인", icon: RefreshCw, tone: "bg-violet-50 text-violet-700" },
  source_changed: { label: "원본 변경", icon: FileWarning, tone: "bg-rose-50 text-rose-700" },
};

// 서버는 UTC ISO 시각을 준다. 사용자의 현지 시각으로 보여준다.
function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ko-KR", { dateStyle: "medium", timeStyle: "short" });
}

export default function NotificationsPage() {
  const router = useRouter();
  const [items, setItems] = useState<NotificationItem[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api.notifications()
      .then(result => { if (!cancelled) setItems(result.items); })
      // 불러오기 실패를 "알림 없음"으로 보이지 않게 따로 표시한다.
      .catch(() => { if (!cancelled) setError("알림을 불러오지 못했습니다. 잠시 후 다시 열어주세요."); });
    return () => { cancelled = true; };
  }, []);

  const markRead = async (item: NotificationItem) => {
    if (item.read_at) return;
    await api.readNotification(item.id);
    setItems(current => current?.map(value => value.id === item.id ? { ...value, read_at: new Date().toISOString() } : value) ?? null);
    announceNotificationsChanged();
  };
  const open = async (item: NotificationItem) => {
    // 읽음 저장이 실패해도 확인하러 가는 이동은 막지 않는다.
    await markRead(item).catch(() => undefined);
    router.push(item.link);
  };
  const readAll = async () => {
    setBusy(true); setError("");
    try {
      await api.readAllNotifications();
      const now = new Date().toISOString();
      setItems(current => current?.map(value => value.read_at ? value : { ...value, read_at: now }) ?? null);
      announceNotificationsChanged();
    } catch {
      setError("모두 읽음으로 바꾸지 못했습니다. 다시 시도해주세요.");
    } finally {
      setBusy(false);
    }
  };

  const unread = items?.filter(item => !item.read_at).length ?? 0;
  return <div className="mx-auto max-w-3xl space-y-5">
    <header className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold text-slate-900"><Bell size={22} className="text-primary" />변화 알림</h1>
        <p className="mt-1 text-sm text-slate-500">검토 중인 후보와 보관한 매물에서 다시 확인할 일이 생기면 알려드립니다.</p>
      </div>
      <button type="button" onClick={() => void readAll()} disabled={busy || unread === 0}
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:border-primary disabled:opacity-40">
        모두 읽음{unread > 0 ? ` (${unread})` : ""}
      </button>
    </header>
    {error && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</p>}

    {items === null && !error ? <p className="py-16 text-center text-sm text-slate-400">불러오는 중...</p>
      : items && items.length === 0 ? <section className="rounded-2xl border border-line bg-white p-8 text-center text-sm text-slate-500">
        <p className="font-semibold text-slate-700">새로 확인할 알림이 없습니다.</p>
        <p className="mt-2">후보 분석의 유효기간이 지나거나, 원본 매물이 바뀌거나, 매물 확인 후 7일이 지나거나, 같은 단지의 실거래가 새로 수집되면 여기에 표시됩니다.</p>
        <Link href="/cases" className="mt-4 inline-block font-semibold text-primary hover:underline">매수 검토 케이스로 이동</Link>
      </section>
      : items && <ul className="space-y-3" aria-label="알림 목록">{items.map(item => {
        const kind = KINDS[item.kind] ?? KINDS.source_changed;
        const Icon = kind.icon;
        return <li key={item.id} className={`rounded-xl border bg-white p-4 shadow-sm ${item.read_at ? "border-line opacity-70" : "border-emerald-200"}`}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-semibold ${kind.tone}`}><Icon size={12} />{kind.label}</span>
            {!item.read_at && <span className="rounded-full bg-primary px-2 py-0.5 font-semibold text-white">새 알림</span>}
            <time dateTime={item.created} className="text-slate-400">{formatTime(item.created)}</time>
          </div>
          <h2 className="mt-2 break-words text-sm font-bold text-slate-900">{item.title}</h2>
          <p className="mt-1 break-words text-sm leading-relaxed text-slate-600">{item.body}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => void open(item)} className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-strong">확인하러 가기</button>
            {!item.read_at && <button type="button" onClick={() => void markRead(item).catch(() => setError("읽음으로 바꾸지 못했습니다."))}
              className="rounded-lg border border-line px-3 py-1.5 text-xs font-semibold text-slate-600 hover:border-primary">읽음</button>}
          </div>
        </li>;
      })}</ul>}

    <p className="text-xs leading-relaxed text-slate-500">
      알림은 이 화면을 열거나 메뉴를 이동할 때 저장된 자료로 다시 계산합니다(메일·푸시는 보내지 않습니다).
      다시 분석하거나 매물을 재확인해 조건이 해결되면 목록에서 사라집니다. 실거래 알림은 서비스가 새로 수집한 신고 거래이며 현재 시세가 아닙니다.
    </p>
  </div>;
}
