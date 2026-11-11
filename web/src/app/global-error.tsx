"use client"; // 오류 경계는 클라이언트 컴포넌트여야 한다.
import "./globals.css";
import { useEffect } from "react";
import { reportClientError } from "@/lib/errorReporting";

// 루트 레이아웃 자체가 실패했을 때만 쓰인다. 레이아웃을 대신하므로 html·body를 직접 그리고, 메뉴·인증 상태에 의존하지 않는다.
export default function GlobalError({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    reportClientError("global", error, error.digest);
  }, [error]);

  return (
    <html lang="ko">
      <body className="grid min-h-screen place-items-center bg-canvas p-4 text-ink">
        <title>오류 | 부동산 컨시어지</title>
        <section className="max-w-md rounded-xl border border-line bg-surface p-6">
          <h1 className="text-lg font-bold">서비스를 표시하지 못했습니다</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-muted">
            잠시 후 다시 시도해주세요. 저장된 기록은 이 오류로 바뀌지 않습니다.
          </p>
          {error.digest && (
            <p className="mt-3 text-xs text-ink-faint">오류 번호: <span className="font-mono">{error.digest}</span></p>
          )}
          <div className="mt-5 flex gap-2">
            <button
              onClick={() => unstable_retry()}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-white"
            >
              다시 시도
            </button>
            {/* 루트 레이아웃이 깨진 상태라 클라이언트 이동(Link) 대신 문서 전체를 새로 불러온다. */}
            <button
              onClick={() => window.location.assign("/")}
              className="rounded-lg border border-line px-4 py-2 text-sm font-semibold"
            >
              홈으로
            </button>
          </div>
        </section>
      </body>
    </html>
  );
}
