import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

// 화면 보안 헤더. Docker(Caddy 뒤)와 Vercel 배포가 같은 값을 쓰도록 Next에서 붙인다.
// - nonce 방식 CSP는 모든 화면을 요청마다 동적 렌더링으로 바꿔 정적 HTML 제공을 잃는다(AGENTS 3-4의 SSR 셸 회귀와 같은 영역).
//   그래서 script-src에 'unsafe-inline'을 두고, 대신 외부 출처를 전부 막는다. 외부 스크립트·이미지·API를 쓰려면 여기 출처를 추가해야 한다.
// - connect-src 'self': 브라우저는 같은 출처 /api만 부른다. 화면 오류도 /api/client-errors로 보낸다(Sentry SDK 미사용).
// - upgrade-insecure-requests는 넣지 않는다. 로컬 http://localhost:3002 요청까지 https로 바꿔 화면이 깨진다. HTTPS 강제는 운영 Caddy의 HSTS가 맡는다.
// - style-src 'unsafe-inline': 차트(recharts)가 style 속성을 쓴다.
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self'",
  `connect-src 'self'${isDev ? " ws: wss:" : ""}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // 현재 화면은 카메라·마이크·위치·결제를 쓰지 않는다. 임장 사진 등을 추가하면 해당 항목을 (self)로 연다.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    return [
      {
        source: "/api/:path*",
        destination: `${apiUrl}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
