"use client";
import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * /reset-password?token=... — 새 비밀번호 설정.
 *
 * useSearchParams 를 쓰는 컴포넌트는 반드시 Suspense 로 감싼다.
 * 이 라우트는 정적 프리렌더 대상이라, 경계가 없으면 프로덕션 빌드가
 * "Missing Suspense boundary with useSearchParams" 로 실패한다.
 * (개발 모드에서는 on-demand 렌더라 그냥 통과해 놓치기 쉽다 —
 *  node_modules/next/dist/docs/01-app/03-api-reference/04-functions/use-search-params.md 참고)
 */
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Shell><p className="text-sm text-slate-400">불러오는 중...</p></Shell>}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white rounded-2xl shadow-lg p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold text-slate-800 mb-1">비밀번호 재설정</h1>
        <p className="text-sm text-slate-400 mb-6">새로 사용할 비밀번호를 입력해주세요.</p>
        {children}
      </div>
    </div>
  );
}

function ResetPasswordForm() {
  const router = useRouter();
  const token  = useSearchParams().get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm]   = useState("");
  const [error, setError]       = useState("");
  const [done, setDone]         = useState(false);
  const [loading, setLoading]   = useState(false);

  if (!token) {
    return (
      <Shell>
        <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-600">
          유효하지 않은 접근입니다. 메일에 포함된 링크로 다시 접속해주세요.
        </div>
        <Link
          href="/forgot-password"
          className="mt-6 block w-full text-center py-2 px-4 bg-primary hover:bg-primary-strong text-white font-medium rounded-lg text-sm transition-colors"
        >
          재설정 링크 다시 받기
        </Link>
      </Shell>
    );
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password.length < 8) { setError("비밀번호는 8자 이상이어야 합니다."); return; }
    if (password !== confirm) { setError("비밀번호가 일치하지 않습니다."); return; }

    setLoading(true);
    try {
      const res = await fetch("/api/auth/password-reset/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, new_password: password }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "재설정에 실패했습니다" }));
        throw new Error(data.detail ?? "재설정에 실패했습니다");
      }
      setDone(true);
      // 비밀번호가 바뀌면 기존 세션은 서버에서 무효화된다 — 로그인 화면으로 보낸다.
      setTimeout(() => router.push("/login"), 2000);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "재설정에 실패했습니다");
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <Shell>
        <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-primary-strong">
          비밀번호가 변경되었습니다.
          <div className="mt-2 text-xs text-primary/70">
            보안을 위해 기존에 로그인되어 있던 모든 기기에서 로그아웃되었습니다.
            잠시 후 로그인 화면으로 이동합니다.
          </div>
        </div>
        <Link
          href="/login"
          className="mt-6 block w-full text-center py-2 px-4 bg-primary hover:bg-primary-strong text-white font-medium rounded-lg text-sm transition-colors"
        >
          지금 로그인하기
        </Link>
      </Shell>
    );
  }

  return (
    <Shell>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">새 비밀번호</label>
          <input
            type="password" required autoFocus minLength={8}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder="8자 이상"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">새 비밀번호 확인</label>
          <input
            type="password" required minLength={8}
            className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
            value={confirm} onChange={(e) => setConfirm(e.target.value)}
          />
        </div>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
        )}

        <button
          type="submit" disabled={loading}
          className="w-full py-2 px-4 bg-primary hover:bg-primary-strong disabled:opacity-50 text-white font-medium rounded-lg text-sm transition-colors"
        >
          {loading ? "변경 중..." : "비밀번호 변경"}
        </button>
      </form>

      <p className="mt-4 text-center text-xs text-slate-400">
        링크는 발송 후 30분간만 유효합니다.
      </p>
    </Shell>
  );
}
