import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(req: NextRequest) {
  const cookie = req.headers.get("cookie") ?? "";

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND}/api/auth/me`, {
      headers: { Cookie: cookie },
    });
  } catch {
    return NextResponse.json(null, { status: 503 });
  }

  if (!backendRes.ok) {
    return NextResponse.json(null, { status: backendRes.status });
  }

  const data = await backendRes.json();
  return NextResponse.json(data);
}

/** 회원 탈퇴 — 백엔드에서 계정·이력 삭제 후 세션 쿠키 제거 */
export async function DELETE(req: NextRequest) {
  const cookie = req.headers.get("cookie") ?? "";

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND}/api/auth/me`, {
      method: "DELETE",
      headers: { Cookie: cookie },
    });
  } catch {
    return NextResponse.json({ detail: "서버에 연결할 수 없습니다" }, { status: 503 });
  }

  if (!backendRes.ok) {
    const err = await backendRes.json().catch(() => ({ detail: "탈퇴 실패" }));
    return NextResponse.json(err, { status: backendRes.status });
  }

  const res = NextResponse.json({ ok: true });
  res.cookies.delete("auth_token");
  return res;
}
