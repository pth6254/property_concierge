"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { setSessionValue } from "@/lib/sessionStore";
import type { ActivityItem } from "@/lib/types";
import {
  Search, Tag, MapPin, TrendingUp, Columns2, ShieldCheck,
  MessageSquareText, ArrowRight, type LucideIcon,
} from "lucide-react";

type StageItem = { href: string; icon: LucideIcon; title: string; desc: string; cta: string };
type Stage = { n: number; step: string; title: string; desc: string; items: StageItem[] };

const STAGES: Stage[] = [
  {
    n: 1, step: "매물 탐색", title: "좋은 물건 찾기",
    desc: "실거래 데이터 기반으로 조건에 맞는 단지를 찾아드립니다.",
    items: [
      {
        href: "/explore", icon: MapPin, title: "동네 탐색",
        desc: "구·동별 실거래를 비교하고 관심 단지의 매물을 찾아보세요.", cta: "동네 찾아보기",
      },
      {
        href: "/listings", icon: MapPin, title: "매물 보관함",
        desc: "네이버에서 찾거나 직접 확인한 매물을 등록해 검토를 이어갑니다.", cta: "매물 등록·확인",
      },
    ],
  },
  {
    n: 2, step: "가치 분석", title: "제값인지 확인하기",
    desc: "시세·수익성·후보 간 비교로 가격의 근거를 만듭니다.",
    items: [
      {
        href: "/appraisal", icon: Tag, title: "AI 시세추정",
        desc: "실거래가 기반으로 적정 시세와 고·저평가 여부를 판단합니다.", cta: "시작하기",
      },
      {
        href: "/simulation", icon: TrendingUp, title: "투자 시뮬레이션",
        desc: "대출·세금을 반영해 수익성을 시나리오별로 검토합니다.", cta: "시작하기",
      },
      {
        href: "/cases", icon: Columns2, title: "후보 검토·비교",
        desc: "케이스에 모은 후보의 시세·자금·위험을 비교하고 선택 근거를 남깁니다.", cta: "케이스에서 이어가기",
      },
    ],
  },
  {
    n: 3, step: "안전 점검", title: "계약 전 위험 거르기",
    desc: "등기부등본으로 깡통전세·가압류 위험을 점검합니다.",
    items: [
      {
        href: "/rights", icon: ShieldCheck, title: "권리관계 위험 점검",
        desc: "등기부등본 PDF를 올리면 근저당·가압류 위험을 분석합니다.", cta: "시작하기",
      },
    ],
  },
  {
    n: 4, step: "법률·세금", title: "궁금한 건 바로 묻기",
    desc: "임대차·세금·상속·증여 질문에 법령 기반으로 답합니다.",
    items: [
      {
        href: "/chat", icon: MessageSquareText, title: "법률·세금 AI 상담",
        desc: "증여세·양도세는 세법 계산기가 자동 실행됩니다.", cta: "질문하기",
      },
    ],
  },
];

const JOURNEY_CHIPS = ["① 매물 탐색", "② 가치 분석", "③ 안전 점검", "④ 법률·세금 상담"];

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

export default function HomePage() {
  const router = useRouter();
  const { user } = useAuth();
  const [recent, setRecent] = useState<ActivityItem[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(true);
  const [heroQuery, setHeroQuery] = useState("");

  useEffect(() => {
    api.activity(6)
      .then(res => setRecent(res.items))
      .catch(() => {})
      .finally(() => setLoadingHistory(false));
  }, []);

  const today = new Date().toLocaleDateString("ko-KR", {
    year: "numeric", month: "long", day: "numeric", weekday: "long",
  });

  const displayName =
    user?.name ||
    (user?.email ? user.email.split("@")[0] : null) ||
    "회원";

  const startFromHero = (e: React.FormEvent) => {
    e.preventDefault();
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

      {/* ── 컨시어지 데스크 (히어로) ── */}
      <section className="rounded-2xl bg-gradient-to-br from-brand to-brand-ink px-6 py-7 text-white shadow-lg md:px-8">
        <p className="mb-2 text-[11px] font-bold uppercase tracking-[0.16em] text-accent">
          Concierge Desk
        </p>
        <h2 className="text-[22px] font-extrabold tracking-tight md:text-2xl">
          어떤 부동산이 궁금하세요?
        </h2>
        <p className="mt-1 mb-4 text-[13.5px] text-white/60">
          주소나 단지명을 입력하면 시세 분석부터 시작해 드립니다.
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
            placeholder="예) 마포구 아현동 마포래미안푸르지오 84㎡"
            aria-label="주소 또는 단지명 검색"
            className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-faint"
          />
          <button
            type="submit"
            className="shrink-0 rounded-lg bg-primary px-5 py-2.5 text-sm font-bold text-white transition-colors hover:bg-primary-strong"
          >
            시세 알아보기
          </button>
        </form>
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
      <div className="space-y-6">
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
              {stage.items.map(({ href, icon: Icon, title, desc, cta }) => (
                <Link
                  key={href}
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
              ))}
            </div>
          </section>
        ))}
      </div>

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
        ) : recent.length === 0 ? (
          <div className="rounded-xl border-2 border-dashed border-line bg-surface p-10 text-center">
            <p className="mb-5 text-sm text-ink-faint">아직 이용 기록이 없습니다.</p>
            <Link
              href="/appraisal"
              className="inline-block rounded-lg bg-primary px-6 py-2.5 text-sm font-semibold text-white transition-colors hover:bg-primary-strong"
            >
              첫 시세추정 시작하기 →
            </Link>
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
