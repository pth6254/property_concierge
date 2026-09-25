import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import Navbar from "@/components/Navbar";
import ConciergeWidget from "@/components/ConciergeWidget";
import { AuthProvider } from "@/lib/auth";

const pretendard = localFont({
  src: "./fonts/PretendardVariable.woff2",
  display: "swap",
  weight: "45 920",
  fallback: ["Apple SD Gothic Neo", "Noto Sans KR", "Malgun Gothic", "sans-serif"],
});

export const metadata: Metadata = {
  title: "부동산 컨시어지",
  description: "매물 탐색부터 시세 분석, 권리 점검, 법률·세금 상담까지 한 곳에서",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" className="h-full">
      <body className={`${pretendard.className} h-full`}>
        <AuthProvider>
          <Navbar />
          <main className="min-h-screen min-w-0 p-4 pb-24 md:ml-[236px] md:p-6 md:pb-24">{children}</main>
          <ConciergeWidget />
        </AuthProvider>
      </body>
    </html>
  );
}
