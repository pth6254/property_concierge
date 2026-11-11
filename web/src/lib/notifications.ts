// 알림을 읽으면 메뉴의 읽지 않은 개수도 바로 갱신한다. 화면과 메뉴가 서로를 직접 참조하지 않도록 창 이벤트로 알린다.
export const NOTIFICATIONS_CHANGED = "notifications:changed";

export function announceNotificationsChanged(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));
}
