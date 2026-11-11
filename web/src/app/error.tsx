"use client"; // 오류 경계는 클라이언트 컴포넌트여야 한다.
import Link from "next/link";
import { useEffect } from "react";
import { reportClientError } from "@/lib/errorReporting";

// 루트 레이아웃(메뉴) 안쪽 화면의 렌더링 오류를 받는다. 메뉴는 그대로 남아 다른 화면으로 이동할 수 있다.
export default function RouteError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    reportClientError("boundary", error, error.digest);
  }, [error]);

  return (
    <section className="mx-auto mt-10 max-w-lg rounded-xl border border-line bg-surface p-6 text-ink">
      <h1 className="text-lg font-bold">화면을 표시하지 못했습니다</h1>
      <p className="mt-2 text-sm leading-relaxed text-ink-muted">
        일시적인 문제일 수 있습니다. 다시 시도해도 같으면 잠시 후 이용하거나 화면 아래 &lsquo;문제·개선 의견 보내기&rsquo;로 알려주세요.
        저장된 매물·케이스·분석 기록은 이 오류로 바뀌지 않습니다.
      </p>
      {error.digest && (
        <p className="mt-3 text-xs text-ink-faint">오류 번호: <span className="font-mono">{error.digest}</span></p>
      )}
      <div className="mt-5 flex flex-wrap gap-2">
        <button
          onClick={() => unstable_retry()}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-strong"
        >
          다시 시도
        </button>
        <Link href="/" className="rounded-lg border border-line px-4 py-2 text-sm font-semibold text-ink hover:border-primary">
          홈으로
        </Link>
      </div>
    </section>
  );
}
