import { NextRequest, NextResponse } from "next/server";

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function POST(req: NextRequest) {
  const body = await req.text();

  let backendRes: Response;
  try {
    backendRes = await fetch(`${BACKEND}/api/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch {
    return NextResponse.json({ detail: "서버에 연결할 수 없습니다" }, { status: 503 });
  }

  const data = await backendRes.text();
  const res = new NextResponse(data, {
    status: backendRes.status,
    headers: { "Content-Type": "application/json" },
  });

  const cookie = backendRes.headers.get("set-cookie");
  if (cookie) res.headers.set("set-cookie", cookie);

  return res;
}
