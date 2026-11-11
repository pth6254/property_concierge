import Link from "next/link";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "페이지를 찾을 수 없음 | 부동산 컨시어지" };

// 없는 주소와 notFound() 호출을 함께 받는다. 다른 사용자의 케이스처럼 접근할 수 없는 자료도
// 서버가 404로 답하므로(AGENTS 2-3) "삭제됐거나 접근할 수 없다"를 구분하지 않고 같은 문구로 안내한다.
export default function NotFound() {
  return (
    <section className="mx-auto mt-10 max-w-lg rounded-xl border border-line bg-surface p-6 text-ink">
      <p className="text-xs font-bold text-ink-faint">404</p>
      <h1 className="mt-1 text-lg font-bold">페이지를 찾을 수 없습니다</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">
        주소가 바뀌었거나 삭제된 자료일 수 있습니다. 진행 중인 검토는 매수 검토 케이스에서 이어갈 수 있습니다.
      </p>
      <div className="mt-5 flex flex-wrap gap-2">
        <Link href="/cases" className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-strong">
          매수 검토 케이스
        </Link>
        <Link href="/" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink hover:border-primary">
          홈으로
        </Link>
      </div>
    </section>
  );
}
