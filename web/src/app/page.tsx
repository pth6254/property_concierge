"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { setSessionValue } from "@/lib/sessionStore";
import { listingEntryHref } from "@/lib/listingNavigation";
import { nextCaseStep } from "@/lib/caseProgress";
import { formatWonKorean } from "@/lib/moneyInput";
import type { ActivityItem, PurchaseCase } from "@/lib/types";
import {
  Search, Tag, MapPin, TrendingUp, Columns2, ShieldCheck, SearchCheck, BriefcaseBusiness,
  MessageSquareText, ArrowRight, type LucideIcon,
} from "lucide-react";

type StageItem = { href: string; icon: LucideIcon; title: string; desc: string; cta: string };
type Stage = { n: number; step: string; title: string; desc: string; items: StageItem[] };

// 핵심 흐름(매물 등록 → 케이스 후보 검토 → 계약 전 점검) 순서로 보여준다.
// 단독 시세추정·시뮬레이션은 후보와 연결되지 않으므로 "빠른 계산"으로 따로 둔다.
const STAGES: Stage[] = [
  {
    n: 1, step: "매물 모으기", title: "검토할 물건 모으기",
    desc: "실거래로 동네를 비교하고, 직접 확인한 매물을 보관합니다.",
    items: [
      { href: "/explore", icon: SearchCheck, title: "동네 탐색", desc: "구·동별 실거래를 비교하고 관심 단지를 찾아보세요.", cta: "동네 찾아보기" },
      { href: "/listings", icon: MapPin, title: "매물 보관함", desc: "포털에서 찾거나 직접 확인한 매물을 등록해 검토를 이어갑니다.", cta: "매물 등록·확인" },
    ],
  },
  {
    n: 2, step: "후보 검토", title: "후보를 비교하고 고르기",
    desc: "케이스에 모은 후보마다 시세·자금·권리를 분석하고 비교합니다.",
    items: [
      { href: "/cases", icon: Columns2, title: "후보 검토·비교", desc: "후보별 시세·자금·권리 분석을 이어가고 선택 근거를 남깁니다.", cta: "케이스에서 이어가기" },
    ],
  },
  {
    n: 3, step: "계약 전 점검", title: "계약 전 위험 거르기",
    desc: "등기부등본 위험 신호와 법률·세금 궁금증을 확인합니다.",
    items: [
      { href: "/rights", icon: ShieldCheck, title: "권리관계 위험 점검", desc: "등기부등본 PDF를 올리면 근저당·가압류 위험 신호를 점검합니다.", cta: "시작하기" },
      { href: "/chat", icon: MessageSquareText, title: "법률·세금 AI 상담", desc: "증여세·양도세는 세법 계산기가 자동 실행됩니다.", cta: "질문하기" },
    ],
  },
];

const QUICK_TOOLS: StageItem[] = [
  { href: "/appraisal", icon: Tag, title: "AI 시세추정", desc: "같은 단지 실거래가 충분하면 참고 시세를 추정하고, 부족하면 보류합니다.", cta: "바로 추정" },
  { href: "/simulation", icon: TrendingUp, title: "투자 시뮬레이션", desc: "대출·세금 조건으로 필요 현금과 수익을 계산합니다.", cta: "바로 계산" },
];

const JOURNEY_CHIPS = ["① 매물 모으기", "② 후보 검토", "③ 계약 전 점검"];
const CASE_STATUS: Record<string, string> = { exploring: "지역 탐색", reviewing: "후보 검토", negotiating: "협상", decided: "결정", archived: "보관" };

const VERDICT_STYLE: Record<string, string> = {
  저평가: "bg-emerald-50 text-emerald-700",
  고평가: "bg-rose-50 text-rose-700",
  적정가: "bg-sky-50 text-sky-700",
};

const TYPE_BADGE: Record<ActivityItem["type"], { label: string; cls: string; href: string }> = {
  appraisal: { label: "시세추정", cls: "bg-emerald-50 text-primary",  href: "/report" },
  rights:    { label: "권리점검", cls: "bg-amber-50 text-amber-700",  href: "/rights" },
  chat:      { label: "상담",     cls: "bg-sky-50 text-sky-700",      href: "/chat" },
};

const RISK_PILL: Record<string, string> = {
  safe:    "bg-emerald-50 text-emerald-700",
  caution: "bg-amber-50 text-amber-700",
  danger:  "bg-rose-50 text-rose-700",
};

function StageCard({ href, icon: Icon, title, desc, cta }: StageItem) {
  return (
    <Link
      href={href}
      className="group flex flex-col gap-2.5 rounded-xl border border-line bg-surface p-4 transition-all hover:-translate-y-px hover:border-primary hover:shadow-md"
    >
      <span className="grid h-9 w-9 place-items-center rounded-lg bg-emerald-50 text-primary">
        <Icon size={17} />
      </span>
      <div className="flex-1">
        <p className="text-sm font-bold text-ink">{title}</p>
        <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{desc}</p>
      </div>
      <span className="flex items-center gap-1 text-xs font-bold text-primary">
        {cta}
        <ArrowRight size={13} className="transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { user } = useAuth();
  const [recent, setRecent] = useState<ActivityItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [historyFailed, setHistoryFailed] = useState(false);
  const [cases, setCases] = useState<PurchaseCase[] | null>(null);
  const [casesFailed, setCasesFailed] = useState(false);
  const [heroQuery, setHeroQuery] = useState("");

  useEffect(() => {
    let cancelled = false;
    // 불러오기 실패를 "기록 없음"으로 보이지 않게 따로 표시한다.
    api.activity(6)
      .then(res => { if (!cancelled) setRecent(res.items); })
      .catch(() => { if (!cancelled) setHistoryFailed(true); })
      .finally(() => { if (!cancelled) setLoadingHistory(false); });
    api.cases()
      .then(res => { if (!cancelled) setCases(res.items); })
      .catch(() => { if (!cancelled) { setCases([]); setCasesFailed(true); } });
    return () => { cancelled = true; };
  }, []);

  const activeCases = (cases ?? []).filter(item => item.status !== "archived")
    .sort((a, b) => b.updated.localeCompare(a.updated)).slice(0, 3);

  const today = new Date().toLocaleDateString("ko-KR", {
    year: "numeric", month: "long", day: "numeric", weekday: "long",
  });

  const displayName =
    user?.name ||
    (user?.email ? user.email.split("@")[0] : null) ||
    "회원";

  // 기본 동작은 매물 등록으로 잇는다. 시세만 보고 싶으면 보조 버튼으로 단독 시세추정에 간다.
  const startFromHero = (e: React.FormEvent) => {
    e.preventDefault();
    router.push(listingEntryHref({ name: heroQuery.trim() || undefined }));
  };
  const quickAppraisal = () => {
    const q = heroQuery.trim();
    if (q) setSessionValue("heroQuery", q);
    router.push("/appraisal");
  };

  return (
    <div className="mx-auto max-w-5xl space-y-8">

      {/* ── 페이지 헤드 ── */}
      <div>
        <p className="text-xs text-ink-faint">{today}</p>
        <h1 className="mt-0.5 text-xl font-extrabold tracking-tight text-ink">
          안녕하세요, <span className="text-primary">{displayName}</span>님.
          오늘은 무엇을 도와드릴까요?
        </h1>
      </div>

      {/* ── 진행 중인 매수 검토: 하던 일을 바로 이어가게 가장 위에 둔다 ── */}
      <section aria-label="진행 중인 매수 검토">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-[15px] font-extrabold tracking-tight text-ink">진행 중인 매수 검토</h2>
          {activeCases.length > 0 && <Link href="/cases" className="text-xs font-semibold text-primary hover:underline">전체 케이스 →</Link>}
        </div>
        {cases === null ? (
          <div className="h-24 animate-pulse rounded-xl border border-line bg-surface" />
        ) : casesFailed ? (
          <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
            매수 검토 케이스를 불러오지 못했습니다. <Link href="/cases" className="font-semibold underline">케이스 목록 열기</Link>
          </p>
        ) : activeCases.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-line bg-surface p-6 text-center">
            <p className="text-sm text-ink-muted">진행 중인 매수 검토가 없습니다. 매수 목표를 만들거나 확인한 매물부터 등록해보세요.</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              <Link href="/cases" className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-strong">새 매수 검토 시작</Link>
              <Link href="/listings" className="rounded-lg border border-line bg-white px-4 py-2 text-sm font-semibold text-primary">매물부터 등록</Link>
            </div>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {activeCases.map(item => {
              const next = nextCaseStep(item);
              return (
                <article key={item.id} className="flex flex-col rounded-xl border border-line bg-surface p-4">
                  <div className="flex items-start justify-between gap-2">
                    <Link href={`/cases/${item.id}`} className="min-w-0 break-words font-bold text-ink hover:text-primary">
                      <BriefcaseBusiness size={15} className="mr-1 inline text-primary" aria-hidden="true" />{item.title}
                    </Link>
                    <span className="shrink-0 rounded-full bg-emerald-50 px-2 py-0.5 text-[11px] font-semibold text-primary">{CASE_STATUS[item.status] ?? item.status}</span>
                  </div>
                  <p className="mt-1 text-xs text-ink-muted">후보 {item.property_count}개 · {item.budget_max ? `예산 ${formatWonKorean(item.budget_max)}` : "예산 미정"}</p>
                  <p className="mt-3 flex-1 text-sm">다음 단계: <strong>{next.label}</strong></p>
                  <Link href={next.href} aria-label={`${item.title} 이어서 하기: ${next.label}`}
                    className="mt-3 inline-flex items-center gap-1 self-start rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-strong">
                    이어서 하기 <ArrowRight size={13} aria-hidden="true" />
                  </Link>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {/* ── 컨시어지 데스크 (히어로) ── */}
      <section className="rounded-2xl bg-gradient-to-br from-brand to-brand-ink px-6 py-7 text-white shadow-lg md:px-8">
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-accent">
          Concierge Desk
        </p>
        <h2 className="text-[22px] font-extrabold tracking-tight md:text-2xl">
          검토할 매물이 있나요?
        </h2>
        <p className="mt-1 mb-4 text-[13.5px] text-white/60">
          단지명이나 주소를 입력하면 매물 등록으로 이어서 후보 검토를 시작합니다.
        </p>
        <form
          onSubmit={startFromHero}
          className="flex max-w-xl items-center gap-2 rounded-xl bg-white p-1.5 pl-4"
        >
          <Search size={18} className="shrink-0 text-ink-muted" />
          <input
            type="text"
            value={heroQuery}
            onChange={e => setHeroQuery(e.target.value)}
            placeholder="예) 마포래미안푸르지오"
            aria-label="단지명 또는 주소"
            className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
          />
          <button
            type="submit"
            className="shrink-0 rounded-lg bg-primary px-5 py-2.5 text-sm font-bold text-white transition-colors hover:bg-primary-strong"
          >
            매물로 등록
          </button>
        </form>
        <button type="button" onClick={quickAppraisal} className="mt-2 text-xs font-semibold text-white/70 underline hover:text-white">
          등록 없이 시세만 먼저 보기
        </button>
        <div className="mt-4 flex flex-wrap items-center gap-1.5" aria-hidden="true">
          {JOURNEY_CHIPS.map((chip, i) => (
            <span key={chip} className="flex items-center gap-1.5">
              <span className="rounded-full border border-white/15 px-2.5 py-0.5 text-[11.5px] text-white/60">
                {chip}
              </span>
              {i < JOURNEY_CHIPS.length - 1 && (
                <span className="text-[11px] text-accent">›</span>
              )}
            </span>
          ))}
        </div>
      </section>

      {/* ── 여정 기반 서비스 ── */}
      <section aria-label="매수 여정" className="space-y-6">
        {STAGES.map(stage => (
          <section key={stage.n} className="grid gap-3 md:grid-cols-[200px_1fr] md:gap-5">
            <div className="pt-1">
              <div className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.12em] text-accent">
                <span className="grid h-5 w-5 place-items-center rounded-full border-[1.5px] border-accent text-[10.5px] tracking-normal">
                  {stage.n}
                </span>
                {stage.step}
              </div>
              <h3 className="mt-1.5 text-base font-extrabold tracking-tight text-ink">
                {stage.title}
              </h3>
              <p className="mt-0.5 text-xs text-ink-muted">{stage.desc}</p>
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {stage.items.map(item => <StageCard key={item.href} {...item} />)}
            </div>
          </section>
        ))}
        <section className="grid gap-3 md:grid-cols-[200px_1fr] md:gap-5">
          <div className="pt-1">
            <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-ink-muted">빠른 계산</div>
            <h3 className="mt-1.5 text-base font-extrabold tracking-tight text-ink">후보 없이 바로 계산</h3>
            <p className="mt-0.5 text-xs text-ink-muted">케이스 후보에 연결되지 않습니다. 후보 분석은 케이스의 후보 카드에서 시작하세요.</p>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {QUICK_TOOLS.map(item => <StageCard key={item.href} {...item} />)}
          </div>
        </section>
      </section>

      {/* ── 최근 활동 ── */}
      <section>
        <div className="mb-3 flex items-baseline justify-between">
          <h3 className="text-[15px] font-extrabold tracking-tight text-ink">최근 활동</h3>
          {recent.length > 0 && (
            <Link href="/dashboard" className="text-xs font-semibold text-primary hover:underline">
              전체 보기 →
            </Link>
          )}
        </div>

        {loadingHistory ? (
          <div className="space-y-px overflow-hidden rounded-xl border border-line bg-surface">
            {[0, 1, 2].map(i => (
              <div key={i} className="flex animate-pulse items-center gap-4 px-5 py-4">
                <div className="h-5 w-16 rounded-full bg-line" />
                <div className="h-4 flex-1 rounded bg-line" />
                <div className="h-4 w-24 rounded bg-line" />
              </div>
            ))}
          </div>
        ) : historyFailed ? (
          <p role="alert" className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">최근 활동을 불러오지 못했습니다. 잠시 후 다시 시도해주세요.</p>
        ) : recent.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-line bg-surface p-8 text-center">
            <p className="text-sm text-ink-faint">아직 이용 기록이 없습니다. 분석을 실행하면 여기에 표시됩니다.</p>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-line bg-surface">
            {recent.map(it => {
              const badge = TYPE_BADGE[it.type] || TYPE_BADGE.appraisal;
              const href = it.type === "appraisal" ? `/report/${it.id}` : badge.href;
              return (
                <Link
                  key={`${it.type}-${it.id}`}
                  href={href}
                  className="flex items-center gap-3 border-b border-line px-5 py-3.5 last:border-b-0 hover:bg-canvas"
                >
                  <span className={`w-[64px] shrink-0 rounded-full px-2 py-1 text-center text-[11px] font-bold ${badge.cls}`}>
                    {badge.label}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13.5px] font-semibold text-ink">
                      {it.type === "chat" ? `"${it.title}"` : it.title}
                    </p>
                    <p className="mt-px truncate text-xs text-ink-muted">
                      {it.type === "appraisal"
                        ? [it.subtitle, it.investment_grade && `등급 ${it.investment_grade}`]
                            .filter(Boolean).join(" · ") || "—"
                        : it.type === "chat"
                        ? (it.tool_used ? `${it.tool_used} 실행` : "법령 기반 답변")
                        : "등기부등본 분석"}
                    </p>
                  </div>
                  <div className="shrink-0 text-right">
                    {it.type === "appraisal" && it.estimated_value ? (
                      <span className="text-[13px] font-bold tabular-nums text-ink">
                        {Math.round(it.estimated_value / 10_000).toLocaleString("ko-KR")}만원
                      </span>
                    ) : null}
                    {it.type === "appraisal" && it.valuation_verdict && (
                      <span
                        className={`ml-2 inline-block rounded-full px-2 py-0.5 text-[11px] font-bold ${
                          VERDICT_STYLE[it.valuation_verdict] || "bg-canvas text-ink-muted"
                        }`}
                      >
                        {it.valuation_verdict}
                      </span>
                    )}
                    {it.type === "rights" && it.subtitle && (
                      <span
                        className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-bold ${
                          RISK_PILL[it.risk_grade || ""] || "bg-canvas text-ink-muted"
                        }`}
                      >
                        {it.subtitle}
                      </span>
                    )}
                  </div>
                  <span className="hidden w-[70px] shrink-0 text-right text-xs tabular-nums text-ink-faint sm:block">
                    {it.created?.slice(0, 10) || "—"}
                  </span>
                </Link>
              );
            })}
          </div>
        )}
      </section>

      {/* ── 하단 안내 ── */}
      <p className="pb-4 text-center text-[11.5px] text-ink-faint">
        본 서비스는 AI 기반 참고용 분석 도구입니다. 실제 계약·투자 결정 시 전문가 자문을 받으세요.
      </p>
    </div>
  );
}
