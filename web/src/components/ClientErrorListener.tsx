"use client";
import { useEffect } from "react";
import { reportClientError, shouldIgnoreWindowError } from "@/lib/errorReporting";

/**
 * error.tsx가 잡지 못하는 오류(이벤트 처리기·타이머·처리되지 않은 Promise 거부)를 보고한다.
 * 화면 상태를 바꾸지 않으므로 effect 안에서 setState를 하지 않는다.
 */
export default function ClientErrorListener() {
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      if (shouldIgnoreWindowError(event.message ?? "", event.filename)) return;
      reportClientError("window", event.error ?? event.message);
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      // 사용자가 화면을 떠나며 취소한 요청은 결함이 아니다.
      if (event.reason instanceof DOMException && event.reason.name === "AbortError") return;
      reportClientError("promise", event.reason);
    };
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
