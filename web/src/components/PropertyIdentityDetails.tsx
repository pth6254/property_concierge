import type { PropertyIdentity } from "@/lib/listings";

export default function PropertyIdentityDetails({ identity }: { identity?: PropertyIdentity | null }) {
  return <div className="mt-2 break-words text-xs text-slate-600">
    <p>동: {identity?.building_dong || "미입력"} · 호: {identity?.unit_number || "미입력"} · 층: {identity?.floor || "미입력"}</p>
    <p>면적 기준: {identity?.area_basis === "exclusive" ? "전용" : identity?.area_basis === "supply" ? "공급" : "미확인"} · 등록한 동·호와 현재 광고·현장 물건의 동일성은 별도 확인이 필요합니다.</p>
  </div>;
}
