"use client";
import { useId, type InputHTMLAttributes } from "react";
import { formatWonKorean, parseWon } from "@/lib/moneyInput";

type Props = Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type"> & {
  value: string;
  onChange: (value: string) => void;
  /** 이 값보다 작으면 단위 실수 가능성을 알린다. 차단하지 않고 사용자가 확인하게 한다. */
  smallWarningBelow?: number;
};

/**
 * 화면마다 만원·원·"7억" 입력이 섞여 있어 0을 네 개 빠뜨리는 실수가 쉬웠다.
 * 모든 금액 칸이 같은 해석(숫자만 = 원, 억·천만·만 단위 허용)을 쓰고, 입력하는 동안 해석 결과를 보여준다.
 */
export default function MoneyInput({ value, onChange, smallWarningBelow = 0, className, ...rest }: Props) {
  const hintId = useId();
  const parsed = value.trim() ? parseWon(value) : null;
  const invalid = parsed != null && !Number.isSafeInteger(parsed);
  const small = parsed != null && !invalid && parsed > 0 && parsed < smallWarningBelow;
  return <span className="block">
    <input {...rest} type="text" inputMode="text" autoComplete="off" value={value} onChange={event => onChange(event.target.value)}
      aria-invalid={invalid || undefined} aria-describedby={hintId}
      className={className ?? "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"} />
    <span id={hintId} aria-live="polite" className={`mt-1 block min-h-4 text-xs ${invalid || small ? "text-amber-700" : "text-slate-500"}`}>
      {parsed == null ? "" : invalid ? "금액 형식을 확인해주세요. 예: 7억 5000만, 75000만, 750000000"
        : `= ${formatWonKorean(parsed)}${small ? " · 부동산 금액으로는 작습니다. 단위(원·만·억)를 확인해주세요" : ""}`}
    </span>
  </span>;
}

/** 입력 문자열을 원으로 바꾼다. 비어 있으면 undefined, 형식이 틀리면 오류를 던져 호출부가 메시지를 보여주게 한다. */
export function wonFromInput(value: string, label: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = parseWon(value);
  if (!Number.isSafeInteger(parsed) || parsed < 0) throw new Error(`${label} 금액 형식을 확인해주세요. 예: 7억 5000만`);
  return parsed;
}
