export type ListingAddressDetails = {
  road_address: string; jibun_address: string; legal_region_code: string;
  latitude: number; longitude: number; building_name: string;
  name_source: "kakao_address" | "building_register" | "unknown";
  name_status: "found" | "unknown" | "ambiguous"; name_candidates: string[];
  source: "kakao_address"; checked_at: string; identity_level: "building" | "parcel";
  parcel_main_no?: string; parcel_sub_no?: string; parcel_mountain?: boolean;
  building_register?: BuildingRegisterEvidence;
};
export type ListingAddressChoice = ListingAddressDetails & { token: string };
export type RegisterFields = Record<string, string | number | null>;
export type RegisterBuilding = { id: string; dong_name: string; building_name: string; auxiliary: boolean; fields: RegisterFields };
export type BuildingRegisterEvidence = {
  source: "building_register"; checked_at: string; status: string; notes: string[];
  record_checked_at?: Record<string, string | null>; area_matches_input?: boolean;
  complex: { fields: RegisterFields } | null; selected_building: RegisterBuilding | null;
  floors: { floor: string; use: string; other_use: string; structure: string; area_sqm: number | null }[];
  unit: { status: string; message?: string; register_id?: string; dong_name?: string; unit_name?: string;
    exclusive_area_sqm?: number | null; floor?: string | null; use?: string; checked_at?: string;
    common_areas?: { area_sqm: number | null; floor: string; use: string }[] };
  zones: { category: string; name: string; other: string }[];
  sanitation: { type: string; capacity_people: number | null; capacity_m3: number | null }[];
};
export type BuildingRegisterResult = BuildingRegisterEvidence & { buildings: RegisterBuilding[]; building_token?: string };
export type PropertyIdentity = {
  building_dong: string; unit_number: string; floor: string; area_basis: "exclusive" | "supply" | "unknown";
  unit_source?: "user_input" | "unknown"; verification_level?: "unit_user_input" | "building_or_parcel";
};

export type ImportedListing = {
  id: number; external_id: string; name: string; source_name: string; source_url: string | null;
  address: string; legal_region_code: string | null; property_type: string; transaction_type: string;
  alias?: string; address_details?: ListingAddressDetails | null;
  identity?: PropertyIdentity; building_dong?: string; unit_number?: string; area_basis?: PropertyIdentity["area_basis"];
  area_sqm: number; floor: string; asking_price: number | null; deposit: number | null; monthly_rent: number | null;
  confirmed_at: string; status: string; needs_confirmation: boolean; region_linked: boolean;
  first_seen_at?: number | null; last_seen_at?: number | null; last_collection_at?: number | null; last_collection_outcome?: string | null;
};
export type ListingObservation = {
  observation_id: number; source_url: string; external_id: string; fetched_at: number; requested_at: number;
  outcome: string; message: string;
  reason_code?: string; upstream_status?: number; retry_after_seconds?: number; retry_at?: number; request_sent?: boolean;
  fields: { name?: string; address?: string; area_sqm?: number; transaction_type?: string; asking_price?: number; deposit?: number; monthly_rent?: number; source_confirmed_date?: string };
};
export type ListingImportResult = {
  valid: boolean; committed: boolean; total: number; created: number; updated: number; unchanged: number; skipped_older: number;
  errors: { row: number; message: string }[]; warnings: { row: number; message: string }[];
  preview: Omit<ImportedListing, "id" | "source_name" | "needs_confirmation" | "region_linked">[];
};
export class ListingRequestError extends Error {
  constructor(message: string, public readonly retryAfterSeconds: number = 0) { super(message); }
}
async function request<T>(path: string, body?: object, timeout = 15000): Promise<T> {
  const response = await fetch(`/api/listings${path}`, { credentials: "include", cache: "no-store", signal: AbortSignal.timeout(timeout),
    ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    const error: { detail?: unknown } = await response.json().catch(() => ({}));
    const retry = Number(response.headers.get("Retry-After"));
    throw new ListingRequestError(typeof error.detail === "string" ? error.detail : "매물 요청을 처리하지 못했습니다. 입력 내용을 확인해주세요.",
      response.status === 429 && Number.isFinite(retry) && retry > 0 ? retry : 0);
  }
  return response.json();
}
export type ListingTimeline = {
  listing_id: number; basis: "service_observed"; transaction_type?: string; needs_confirmation?: boolean;
  points: { confirmed_at: string; imported_at: string; status: string; asking_price: number | null; deposit: number | null; monthly_rent: number | null }[];
  metrics: { key: string; label: string; initial: number; current: number; change_count: number; lowest: number; highest: number; cumulative_change_pct: number | null }[];
  status_changes: { at: string; from: string; to: string }[];
  period: { first_confirmed_at: string; last_confirmed_at: string; days: number; saved_versions: number } | null;
  collection: { attempts: number; observed: number; unreadable: number; last_attempt_at: string | null; last_outcome?: string;
    recent: { fetched_at: string; outcome: string; differs_from_saved?: boolean; differing_fields?: string[];
      observed_asking_price?: number; observed_deposit?: number; observed_monthly_rent?: number }[] };
  limitations: string[];
};
export type ListingMarketOverlay = {
  listing_id: number; applicable: boolean; reason: string;
  asking: { price_won: number | null; per_sqm_won: number | null; confirmed_at: string };
  trades: null | { available: boolean; reason?: string; complex_name?: string; match?: string; data_through?: string; window_months?: number; area_tolerance_pct?: number;
    trades: { deal_date: string; floor: string; area_sqm: number; price_won: number; price_per_sqm_won: number }[] };
  summary: { recent_window_months: number; recent_count: number; status: "ok" | "insufficient" | "no_trades" | "no_asking";
    recent_median_per_sqm_won: number | null; asking_vs_recent_median_pct: number | null };
  avm: { property_id: number; case_id: number; status: string; analyzed_at: string; shown: boolean; estimated_value_won: number | null; note: string }[];
  limitations: string[];
};
export const listingApi = {
  addresses: (query: string) => request<{items:ListingAddressChoice[]}>(`/address/search?${new URLSearchParams({query})}`, undefined, 25000),
  building: (input: {address_token: string; building_id?: string; building_dong?: string; unit_number?: string; property_type: string}) =>
    request<BuildingRegisterResult>("/address/building", input, 60000),
  get: (id: number) => request<ImportedListing>(`/${id}`),
  collect: (source_url: string) => request<{job_id:string}>("/collection/jobs", {source_url}),
  collectionJob: (id: string) => request<{status:string; error:string; result?:ListingObservation}>(`/collection/jobs/${encodeURIComponent(id)}`),
  observations: (source_url: string) => request<{items:ListingObservation[]}>(`/collection/history?${new URLSearchParams({source_url})}`),
  import: (source_name: string, csv_text: string, commit = false) => request<ListingImportResult>("/import", {source_name, csv_text, commit}),
  search: (params: URLSearchParams) => request<{items: ImportedListing[]; total: number}>(`?${params}`),
  confirm: (id: number, body: { confirmed_at: string; status: string; asking_price?: number; deposit?: number; monthly_rent?: number }) =>
    request<ImportedListing>(`/${id}/confirm`, body),
  marketOverlay: (id: number) => request<ListingMarketOverlay>(`/${id}/market-overlay`, undefined, 30000),
  timeline: (id: number) => request<ListingTimeline>(`/${id}/timeline`),
  history: (id: number) => request<{items: (ImportedListing & {imported_at: string})[]}>(`/${id}/history`),
  saveCandidate: (id: number, case_id: number) => request<{id:number}>(`/${id}/candidate`, {case_id}),
};
