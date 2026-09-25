export type ImportedListing = {
  id: number; external_id: string; name: string; source_name: string; source_url: string | null;
  address: string; legal_region_code: string | null; property_type: string; transaction_type: string;
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
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`/api/listings${path}`, { credentials: "include", cache: "no-store", signal: AbortSignal.timeout(15000),
    ...(body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  if (!response.ok) {
    const error: { detail?: unknown } = await response.json().catch(() => ({}));
    const retry = Number(response.headers.get("Retry-After"));
    throw new ListingRequestError(typeof error.detail === "string" ? error.detail : "매물 요청을 처리하지 못했습니다. 입력 내용을 확인해주세요.",
      response.status === 429 && Number.isFinite(retry) && retry > 0 ? retry : 0);
  }
  return response.json();
}
export const listingApi = {
  get: (id: number) => request<ImportedListing>(`/${id}`),
  collect: (source_url: string) => request<{job_id:string}>("/collection/jobs", {source_url}),
  collectionJob: (id: string) => request<{status:string; error:string; result?:ListingObservation}>(`/collection/jobs/${encodeURIComponent(id)}`),
  observations: (source_url: string) => request<{items:ListingObservation[]}>(`/collection/history?${new URLSearchParams({source_url})}`),
  import: (source_name: string, csv_text: string, commit = false) => request<ListingImportResult>("/import", {source_name, csv_text, commit}),
  search: (params: URLSearchParams) => request<{items: ImportedListing[]; total: number}>(`?${params}`),
  history: (id: number) => request<{items: (ImportedListing & {imported_at: string})[]}>(`/${id}/history`),
  saveCandidate: (id: number, case_id: number) => request<{id:number}>(`/${id}/candidate`, {case_id}),
};
