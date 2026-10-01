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
