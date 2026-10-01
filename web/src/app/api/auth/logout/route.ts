import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const cookie = req.headers.get("cookie") ?? "";

  try {
    await fetch(`${BACKEND}/api/auth/logout`, {
      method: "POST",
      headers: { Cookie: cookie },
    });
  } catch {
    // 백엔드 실패해도 클라이언트 쿠키는 삭제
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.delete("auth_token");
  return res;
}
