"use client";
import { useSyncExternalStore } from "react";

/**
 * sessionStore — 페이지 간 일회성 데이터 전달(handoff)용 sessionStorage 래퍼.
 *
 * 왜 sessionStorage 를 컴포넌트에서 직접 읽지 않는가:
 *
 *   1. `useEffect` 에서 읽어 `setState` 하면 마운트마다 연쇄 렌더가 발생한다
 *      (React 19 의 react-hooks/set-state-in-effect 규칙이 잡아낸다).
 *   2. `useState` 초기화 함수에서 읽으면 서버 렌더 결과(값 없음)와 달라져
 *      하이드레이션 불일치가 난다 — 이 페이지들은 정적 프리렌더되므로 실제 위험이다.
 *
 * `useSyncExternalStore` 는 서버 스냅샷과 클라이언트 스냅샷을 분리해 둘 다 피한다.
 * 대신 스냅샷이 "값이 바뀌지 않았으면 같은 값"이어야 하므로, 값 변경을 구독으로
 * 알려야 한다 — 그래서 쓰기도 반드시 이 모듈의 set/remove 를 거쳐야 한다.
 * (raw sessionStorage.setItem 으로 쓰면 읽는 쪽이 갱신되지 않는다.)
 */

type Listener = () => void;

const listeners = new Set<Listener>();

function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

function emit(): void {
  listeners.forEach((l) => l());
}

export function setSessionValue(key: string, value: string): void {
  sessionStorage.setItem(key, value);
  emit();
}

export function removeSessionValue(key: string): void {
  sessionStorage.removeItem(key);
  emit();
}

/**
 * sessionStorage 값을 SSR-안전하게 구독한다.
 *
 * 반환값은 3-상태다 — "아직 못 읽음"과 "읽었는데 없음"을 구분해야
 * 하이드레이션 시점에 빈 상태 UI가 한 번 스쳤다 사라지는 것을 막을 수 있다.
 *
 *   undefined — 아직 클라이언트에서 읽기 전 (SSR·하이드레이션 시점)
 *   null      — 읽었으나 값이 없음
 *   string    — 저장된 값
 */
export function useSessionValue(key: string): string | null | undefined {
  return useSyncExternalStore(
    subscribe,
    () => sessionStorage.getItem(key),
    () => undefined,
  );
}
