import type { PropertyIdentity } from "@/lib/listings";

export default function PropertyIdentityFields({ identity }: { identity?: PropertyIdentity | null }) {
  const style = "mt-1 w-full rounded-lg border border-slate-300 p-2";
  return <div className="grid gap-3 text-sm sm:grid-cols-2">
    <label>건물 동 (선택)<input name="building_dong" maxLength={30} defaultValue={identity?.building_dong ?? ""} className={style} placeholder="예: 101" /></label>
    <label>호수 (선택)<input name="unit_number" maxLength={30} defaultValue={identity?.unit_number ?? ""} className={style} placeholder="예: 501" /></label>
    <label>층 (선택)<input name="floor" maxLength={30} defaultValue={identity?.floor ?? ""} className={style} placeholder="예: 5층" /></label>
    <label>면적 기준<select aria-label="면적 기준" name="area_basis" defaultValue={identity?.area_basis ?? "unknown"} className={style}><option value="unknown">확인 필요</option><option value="exclusive">전용면적</option><option value="supply">공급면적</option></select></label>
    <p className="text-xs text-slate-500 sm:col-span-2">동·호는 선택 입력입니다. 주소 조회 결과만으로 개별 호의 동일성을 확인하지 않습니다.</p>
  </div>;
}

export function identityFromForm(form: HTMLFormElement) {
  const data = new FormData(form);
  const value = (name: string) => String(data.get(name) ?? "").trim();
  const raw = value("area_basis");
  const area_basis: PropertyIdentity["area_basis"] = raw === "exclusive" || raw === "supply" ? raw : "unknown";
  return { building_dong: value("building_dong"), unit_number: value("unit_number"), floor: value("floor"), area_basis };
}
