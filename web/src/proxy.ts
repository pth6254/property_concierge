import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const AUTH_PAGES   = ["/login", "/register"];          // 로그인 상태면 접근 불필요
// 로그인 여부와 무관하게 공개.
// 비밀번호 재설정은 AUTH_PAGES 가 아니라 여기 둔다 — 로그인된 상태에서 메일의
// 재설정 링크를 눌렀을 때 홈으로 튕겨내면 재설정을 할 수 없기 때문이다.
const OPEN_PAGES   = ["/privacy", "/terms", "/forgot-password", "/reset-password"];

// Vercel 배포에서만 설정한다(서버 전용, NEXT_PUBLIC 아님). Docker에서는 Caddy가 /api를 Spring으로 바로 보내
// 이 경로를 지나지 않는다.
const EDGE_PROXY_SECRET = process.env.EDGE_PROXY_SECRET ?? "";

function clientIp(request: NextRequest): string {
  // Vercel이 덮어쓰는 접속 IP 헤더만 쓴다. 클라이언트가 보낸 값은 아래에서 우리 헤더로 덮어쓴다.
  const forwarded = request.headers.get("x-forwarded-for")?.split(",")[0]?.trim();
  return request.headers.get("x-real-ip")?.trim() || forwarded || "";
}

function forwardApi(request: NextRequest) {
  // Vercel을 거치면 Spring에는 Vercel 서버 IP만 보인다. 그러면 로그인 잠금·레이트 리밋이 모든 사용자에게 함께 걸린다(AGENTS 2-5).
  // 실제 접속 IP를 공유 비밀과 함께 넘기고, 백엔드 Caddy(infrastructure/proxy/Caddyfile.api)는 비밀이 맞을 때만 그 IP를 Spring에 전달한다.
  const headers = new Headers(request.headers);
  headers.delete("x-edge-proxy-secret");
  headers.delete("x-client-ip");
  if (EDGE_PROXY_SECRET) {
    headers.set("x-edge-proxy-secret", EDGE_PROXY_SECRET);
    const ip = clientIp(request);
    if (ip) headers.set("x-client-ip", ip);
  }
  return NextResponse.next({ request: { headers } });
}

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (pathname.startsWith("/api/") || pathname === "/api") {
    return forwardApi(request);
  }

  const token = request.cookies.get("auth_token");

  if (OPEN_PAGES.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const isAuthPage = AUTH_PAGES.some((p) => pathname.startsWith(p));

  if (!token && !isAuthPage) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // 로그인 직후와 같은 곳(홈의 진행 중 케이스)으로 보낸다.
  if (token && isAuthPage) {
    return NextResponse.redirect(new URL("/", request.url));
  }

  return NextResponse.next();
}

export const config = {
  // /api도 포함한다: Vercel에서 리라이트로 넘기기 전에 접속 IP·비밀 헤더를 붙여야 한다.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
