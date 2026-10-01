import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const AUTH_PAGES   = ["/login", "/register"];          // 로그인 상태면 접근 불필요
// 로그인 여부와 무관하게 공개.
// 비밀번호 재설정은 AUTH_PAGES 가 아니라 여기 둔다 — 로그인된 상태에서 메일의
// 재설정 링크를 눌렀을 때 /appraisal 로 튕겨내면 재설정을 할 수 없기 때문이다.
const OPEN_PAGES   = ["/privacy", "/terms", "/forgot-password", "/reset-password"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const token = request.cookies.get("auth_token");

  if (OPEN_PAGES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const isAuthPage = AUTH_PAGES.some((p) => pathname.startsWith(p));

  if (!token && !isAuthPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  if (token && isAuthPage) {
    return NextResponse.redirect(new URL("/appraisal", request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api|_next/static|_next/image|favicon.ico).*)"],
};
