/** 소수 억·복합 단위 입력을 자릿수 문자열 연결 없이 원으로 환산한다. */
export function parseWon(input: string): number {
  const value = input.replace(/[\s,]/g, "").replace(/원$/, "");
  if (!value) return 0;
  if (/^\d+$/.test(value)) {
    const amount = Number(value);
    return Number.isSafeInteger(amount) ? amount : NaN;
  }
  const match = /^(?:(\d+(?:\.\d+)?)억)?(?:(\d+(?:\.\d+)?)천만)?(?:(\d+(?:\.\d+)?)만)?$/.exec(value);
  if (!match || !match[0]) return NaN;
  const amount = Number(match[1] ?? 0) * 100000000 + Number(match[2] ?? 0) * 10000000 + Number(match[3] ?? 0) * 10000;
  return Number.isSafeInteger(amount) ? amount : NaN;
}

/** 원 단위 금액을 "7억 5,000만원"처럼 읽기 쉬운 형태로 바꾼다. 만원 미만은 원까지 표시해 반올림으로 값을 숨기지 않는다. */
export function formatWonKorean(amount: number): string {
  if (!Number.isFinite(amount)) return "";
  if (amount === 0) return "0원";
  const sign = amount < 0 ? "-" : "";
  let rest = Math.abs(Math.trunc(amount));
  const eok = Math.floor(rest / 100_000_000); rest %= 100_000_000;
  const man = Math.floor(rest / 10_000); rest %= 10_000;
  const parts = [eok ? `${eok.toLocaleString("ko-KR")}억` : "", man ? `${man.toLocaleString("ko-KR")}만` : "", rest ? rest.toLocaleString("ko-KR") : ""].filter(Boolean);
  return `${sign}${parts.join(" ")}원`;
}
