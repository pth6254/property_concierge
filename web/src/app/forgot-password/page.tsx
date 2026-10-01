"use client";
import { useState } from "react";
import Link from "next/link";

/**
 * /forgot-password — 재설정 링크 요청.
 *
 * 백엔드는 계정 존재 여부와 무관하게 항상 같은 응답을 준다(계정 열거 방지).
 * 화면도 그 원칙을 그대로 따라야 한다 — "가입되지 않은 이메일입니다" 같은
 * 안내를 여기서 만들어내면 서버가 막아둔 정보가 UI 로 새어나간다.
 */
export default function ForgotPasswordPage() {
  const [email, setEmail]     = useState("");
  const [sent, setSent]       = useState(false);
  const [error, setError]     = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await fetch("/api/auth/password-reset/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "요청에 실패했습니다" }));
        throw new Error(data.detail ?? "요청에 실패했습니다");
      }
      setSent(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "요청에 실패했습니다");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-50">
      <div className="bg-white rounded-2xl shadow-lg p-8 w-full max-w-sm">
        <h1 className="text-2xl font-bold text-slate-800 mb-1">비밀번호 찾기</h1>
        <p className="text-sm text-slate-400 mb-6">
          가입하신 이메일로 재설정 링크를 보내드립니다.
        </p>

        {sent ? (
          <>
            <div className="rounded-lg bg-emerald-50 border border-emerald-200 px-4 py-3 text-sm text-primary-strong">
              입력하신 이메일로 재설정 링크를 보냈습니다. 메일함을 확인해주세요.
              <div className="mt-2 text-xs text-primary/70">
                링크는 30분간 유효합니다. 메일이 오지 않으면 스팸함도 확인해보세요.
              </div>
            </div>
            <Link
              href="/login"
              className="mt-6 block w-full text-center py-2 px-4 bg-primary hover:bg-primary-strong text-white font-medium rounded-lg text-sm transition-colors"
            >
              로그인으로 돌아가기
            </Link>
          </>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-slate-700 mb-1">이메일</label>
              <input
                type="email" required autoFocus
                className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/40"
                value={email} onChange={(e) => setEmail(e.target.value)}
                placeholder="가입하신 이메일 주소"
              />
            </div>

            {error && (
              <p className="text-sm text-red-600 bg-red-50 rounded-lg px-3 py-2">{error}</p>
            )}

            <button
              type="submit" disabled={loading}
              className="w-full py-2 px-4 bg-primary hover:bg-primary-strong disabled:opacity-50 text-white font-medium rounded-lg text-sm transition-colors"
            >
              {loading ? "전송 중..." : "재설정 링크 받기"}
            </button>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-slate-500">
          <Link href="/login" className="text-primary hover:underline font-medium">
            로그인으로 돌아가기
          </Link>
        </p>

        <p className="mt-3 text-center text-xs text-slate-400">
          Google 계정으로 가입하셨다면 비밀번호가 없습니다 — Google 로그인을 이용해주세요.
        </p>
      </div>
    </div>
  );
}
