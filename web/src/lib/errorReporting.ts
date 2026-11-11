// 화면 오류를 Spring(/api/client-errors)으로 보낸다. Spring이 SENTRY_DSN이 있으면 Sentry로, 없으면 로그로 남긴다.
// 브라우저에 Sentry SDK·DSN을 두지 않는 이유: CSP connect-src를 'self'로 유지하고, 광고 차단기에 막히지 않으며, 번들이 커지지 않는다.
// 대신 스택은 압축된 번들 기준이다. 원인 위치는 digest·경로·문구로 로컬에서 재현한다.

export type ClientErrorKind = "boundary" | "global" | "window" | "promise";

// 같은 오류가 렌더링마다 반복돼 요청이 쏟아지지 않도록 페이지 수명 동안 종류·문구별로 한 번, 최대 10건만 보낸다.
const sent = new Set<string>();
const MAX_REPORTS = 10;

function describe(value: unknown): { message: string; stack?: string } {
  if (value instanceof Error) return { message: value.message || value.name, stack: value.stack };
  if (typeof value === "string") return { message: value };
  try {
    return { message: JSON.stringify(value) ?? String(value) };
  } catch {
    return { message: String(value) };
  }
}

export function reportClientError(kind: ClientErrorKind, error: unknown, digest?: string): void {
  if (typeof window === "undefined") return;
  const { message, stack } = describe(error);
  const key = `${kind}:${digest ?? ""}:${message}`;
  if (sent.has(key) || sent.size >= MAX_REPORTS) return;
  sent.add(key);
  const body = JSON.stringify({
    kind,
    message: message.slice(0, 2000),
    // 질의 문자열에는 검색어·주소가 들어갈 수 있어 경로만 보낸다. 서버가 숫자 ID도 가린다.
    path: window.location.pathname.slice(0, 300),
    digest: digest?.slice(0, 100),
    stack: stack?.slice(0, 8000),
  });
  // 페이지를 떠나는 중에도 전송되도록 keepalive를 쓴다. 보고 실패가 화면 동작을 막지 않게 오류는 무시한다.
  fetch("/api/client-errors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body,
    keepalive: true,
  }).catch(() => undefined);
}

// 브라우저 확장 프로그램·외부 스크립트 오류와 브라우저 자체의 무해한 경고는 서비스 결함이 아니다.
const IGNORED_MESSAGES = [/ResizeObserver loop/i, /^Script error\.?$/i];

export function shouldIgnoreWindowError(message: string, filename?: string): boolean {
  if (IGNORED_MESSAGES.some(pattern => pattern.test(message))) return true;
  if (filename && typeof window !== "undefined") {
    try {
      return new URL(filename, window.location.href).origin !== window.location.origin;
    } catch {
      return false;
    }
  }
  return false;
}
