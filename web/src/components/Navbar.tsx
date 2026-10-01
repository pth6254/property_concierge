"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { useAuth } from "@/lib/auth";
import {
  Home, Tag, MapPin, TrendingUp, Columns2, ShieldCheck,
  MessageSquareText, FileText, History, Menu, X, BriefcaseBusiness, SearchCheck,
  type LucideIcon,
} from "lucide-react";

type NavItem = { href: string; label: string; icon: LucideIcon; exact?: boolean };
type NavGroup = { label: string | null; items: NavItem[] };

const GROUPS: NavGroup[] = [
  {
    label: null,
    items: [{ href: "/", label: "홈", icon: Home, exact: true }],
  },
  {
    label: "의사결정",
    items: [
      { href: "/explore", label: "동네 탐색", icon: SearchCheck },
      { href: "/listings", label: "매물 보관함", icon: MapPin },
      { href: "/cases", label: "매수 검토 케이스", icon: BriefcaseBusiness },
    ],
  },
  {
    label: "분석",
    items: [
      { href: "/appraisal",      label: "AI 시세추정",     icon: Tag },
      { href: "/simulation",     label: "투자 시뮬레이션", icon: TrendingUp },
    ],
  },
  {
    label: "안전·상담",
    items: [
      { href: "/rights", label: "권리관계 점검", icon: ShieldCheck },
      { href: "/chat",   label: "법률·세금 AI",  icon: MessageSquareText },
    ],
  },
  {
    label: "추가 도구",
    items: [
      { href: "/recommendation", label: "단지 추천·샘플", icon: MapPin },
      { href: "/comparison", label: "샘플 매물 비교", icon: Columns2 },
    ],
  },
  {
    label: "내 기록",
    items: [
      { href: "/report",    label: "결과 리포트",     icon: FileText },
      { href: "/dashboard", label: "이력 대시보드",   icon: History },
    ],
  },
];

function Wordmark() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-white">
        <Home size={17} />
      </span>
      <span className="text-[17px] font-extrabold tracking-tight text-white">
        부동산 <em className="not-italic text-accent">컨시어지</em>
      </span>
    </div>
  );
}

function NavList({ path, onNavigate }: { path: string; onNavigate?: () => void }) {
  return (
    <nav className="flex-1 overflow-y-auto px-2.5 py-3">
      {GROUPS.map((group, gi) => (
        <div key={gi} className="mb-4">
          {group.label && (
            <div className="mb-1.5 px-3 text-[10.5px] font-bold uppercase tracking-[0.14em] text-white/40">
              {group.label}
            </div>
          )}
          {group.items.map(({ href, label, icon: Icon, exact }) => {
            const active = exact
              ? path === href
              : path === href || path.startsWith(href + "/");
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                onClick={onNavigate}
                className={`relative mb-0.5 flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13.5px] transition-colors ${
                  active
                    ? "bg-white/10 font-semibold text-white"
                    : "text-white/60 hover:bg-white/5 hover:text-white"
                }`}
              >
                {active && (
                  <span className="absolute -left-2.5 top-1.5 bottom-1.5 w-[3px] rounded bg-accent" />
                )}
                <Icon size={16} className="shrink-0 opacity-85" />
                {label}
              </Link>
            );
          })}
        </div>
      ))}
    </nav>
  );
}

function UserFooter() {
  const { user, logout, withdraw } = useAuth();

  const handleWithdraw = async () => {
    if (!window.confirm("회원 탈퇴 시 계정과 모든 이용 기록(시세추정 이력·활동)이 즉시 삭제되며 복구할 수 없습니다.\n정말 탈퇴하시겠습니까?")) return;
    try {
      await withdraw();
    } catch (e) {
      window.alert(e instanceof Error ? e.message : "탈퇴에 실패했습니다. 잠시 후 다시 시도해주세요.");
    }
  };

  return (
    <div className="space-y-2 border-t border-white/10 px-5 py-4">
      {user && (
        <>
          <div className="truncate text-xs font-semibold text-white/90">
            {user.name || user.email}
          </div>
          <div className="truncate text-xs text-white/40">{user.email}</div>
          {user.is_operator && <Link href="/operations" className="block py-2 text-sm text-white underline">운영 관리</Link>}
          <div className="flex gap-1.5">
            <button
              onClick={logout}
              className="rounded-md border border-white/20 px-2.5 py-1 text-[11.5px] text-white/60 transition-colors hover:border-white/40 hover:text-white"
            >
              로그아웃
            </button>
            <button
              onClick={handleWithdraw}
              className="rounded-md px-2 py-1 text-[11.5px] text-white/30 transition-colors hover:text-rose-300"
            >
              회원 탈퇴
            </button>
          </div>
        </>
      )}
      <div className="flex gap-2 text-[11px]">
        <Link href="/privacy" className="text-white/40 hover:text-white/70 hover:underline">개인정보처리방침</Link>
        <Link href="/terms" className="text-white/40 hover:text-white/70 hover:underline">이용약관</Link>
      </div>
      <div className="text-[11px] text-white/50">실거래·사용자 등록 자료 · 참고용</div>
    </div>
  );
}

/**
 * 모바일 상단바 + 드로어.
 *
 * 드로어 열림 상태는 경로가 바뀌면 닫혀야 한다. 이전에는 useEffect 에서
 * setOpen(false) 를 호출했지만, 그건 effect 안의 동기 setState 라 연쇄 렌더를
 * 유발한다(react-hooks/set-state-in-effect). 대신 Navbar 가 이 컴포넌트에
 * `key={path}` 를 주어, 경로가 바뀌면 컴포넌트가 새로 마운트되며 open 이
 * 자연스럽게 초기값(false)으로 돌아가게 한다 — React 가 권장하는
 * "prop 이 바뀌면 key 로 상태 초기화" 패턴이다.
 *
 * 링크 클릭뿐 아니라 브라우저 뒤로가기 같은 경로 변경에도 동일하게 동작한다.
 */
function MobileNav({ path }: { path: string }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* 모바일 상단바 */}
      <div className="no-print sticky top-0 z-50 flex items-center justify-between bg-brand px-4 py-3 md:hidden">
        <Wordmark />
        <button
          onClick={() => setOpen(true)}
          aria-label="메뉴 열기"
          className="rounded-md p-1 text-white/80 hover:text-white"
        >
          <Menu size={22} />
        </button>
      </div>

      {/* 모바일 드로어 */}
      {open && (
        <div className="fixed inset-0 z-[60] md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setOpen(false)}
            aria-hidden="true"
          />
          <div className="absolute left-0 top-0 flex h-full w-[260px] flex-col bg-brand text-white shadow-xl">
            <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
              <Wordmark />
              <button
                onClick={() => setOpen(false)}
                aria-label="메뉴 닫기"
                className="rounded-md p-1 text-white/70 hover:text-white"
              >
                <X size={20} />
              </button>
            </div>
            <NavList path={path} onNavigate={() => setOpen(false)} />
            <UserFooter />
          </div>
        </div>
      )}
    </>
  );
}

export default function Navbar() {
  const path = usePathname();

  return (
    <>
      {/* 데스크톱 사이드바 */}
      <aside className="no-print fixed left-0 top-0 z-50 hidden h-full w-[236px] flex-col bg-brand text-white shadow-lg md:flex">
        <div className="border-b border-white/10 px-5 py-5">
          <Wordmark />
          <div className="mt-2 text-[11.5px] text-white/50">
            매물 탐색부터 계약·세금까지, 한 곳에서
          </div>
        </div>
        <NavList path={path} />
        <UserFooter />
      </aside>

      <MobileNav key={path} path={path} />
    </>
  );
}
