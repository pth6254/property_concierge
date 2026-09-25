import type { ActivityItem, CaseCandidateComparison, CaseExecution, CaseProperty, ComplexAddress, ConciergeResponse, ExecutionActor, ExecutionPhase, ExecutionTaskStatus, PurchaseCase, RecommendationRequest, SimulationRequest } from "./types";

const BASE = "/api";

export class ConversationJobError extends Error {}

async function conversationJob<T>(path: string, body: object): Promise<T> {
  const started = await req<{ job_id: string }>(path, {
    method: "POST", body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
  });
  const deadline = Date.now() + 240000;
  while (Date.now() < deadline) {
    const job = await req<{ status: string; result?: T; error?: string }>(`${path}/${started.job_id}`, { signal: AbortSignal.timeout(15000) });
    if (job.status === "done" && job.result) return job.result;
    if (job.status === "error") throw new ConversationJobError(job.error || "답변 생성에 실패했습니다.");
    await new Promise(resolve => setTimeout(resolve, 1000));
  }
  throw new ConversationJobError("답변 대기 시간이 초과되었습니다. 잠시 후 다시 확인해주세요.");
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    ...init,
  });
  if (!res.ok) {
    const msg = await res.text().catch(() => `HTTP ${res.status}`);
    throw new Error(msg);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  conciergeConversation: async (conversationId: string, signal?: AbortSignal) => {
    const response = await fetch(`${BASE}/concierge/conversations/${encodeURIComponent(conversationId)}`, {
      credentials: "include", cache: "no-store", signal,
    });
    if (response.status === 404 || response.status === 422) return null;
    if (!response.ok) throw new Error("대화를 복원하지 못했습니다.");
    return response.json() as Promise<{
      conversation_id: string;
      candidate_context: { case_id?: number; candidate_id?: number | null };
      messages: { role: "user" | "assistant"; content: string; response?: ConciergeResponse }[];
    }>;
  },
  appraisal: (
    userInput: string,
    buildingName = "",
    saveHistory = true,
    appraisalDate = "",      // YYYYMMDD
    appraisalPurpose = "",   // 담보/경매/과세/매매/보상/임의
  ) =>
    req("/appraisal", {
      method: "POST",
      body: JSON.stringify({
        user_input:        userInput,
        building_name:     buildingName,
        save_history:      saveHistory,
        appraisal_date:    appraisalDate,
        appraisal_purpose: appraisalPurpose,
      }),
    }),

  /** 비동기 시세추정 작업 시작 → { job_id } */
  appraisalJobStart: (
    userInput: string,
    buildingName = "",
    saveHistory = true,
    appraisalDate = "",
    appraisalPurpose = "",
    address = "",
    propertyCategory = "",
    propertyDetail = "",
    caseId?: number,
    candidateId?: number,
    areaSqm?: number,
  ) =>
    req<{ job_id: string }>("/appraisal/jobs", {
      method: "POST",
      body: JSON.stringify({
        user_input:        userInput,
        building_name:     buildingName,
        save_history:      saveHistory,
        appraisal_date:    appraisalDate,
        appraisal_purpose: appraisalPurpose,
        address,
        property_category: propertyCategory,
        property_detail:   propertyDetail,
        case_id:            caseId,
        candidate_id:       candidateId,
        area_sqm:           areaSqm,
      }),
    }),

  /**
   * 작업 상태 폴링 → { status, step, history_id?, result? }
   *
   * signal 을 넘기면 페이지 이탈 시 진행 중인 요청을 취소할 수 있다
   * (폴링은 수 분간 반복되므로 취소 수단이 없으면 유령 요청이 남는다).
   */
  appraisalJob: (jobId: string, signal?: AbortSignal) =>
    req<{
      job_id: string;
      status: "queued" | "running" | "done" | "error";
      step: string;
      error: string;
      history_id?: number;
      result?: Record<string, unknown>;
    }>(`/appraisal/jobs/${jobId}`, { signal }),

  recommendation: (params: RecommendationRequest) =>
    req("/recommendation", { method: "POST", body: JSON.stringify(params) }),

  /** 실거래 기반 단지 추천 (전국) — 금액 단위: 만원 */
  recommendComplexes: (params: {
    region: string;
    region_code?: string;
    budget_min?: number;
    budget_max?: number;
    area_m2?: number;
    months?: number;
    limit?: number;
  }) =>
    req<{
      region: string;
      sample_count: number;
      complex_count: number;
      region_avg_per_sqm: number;
      results: (ComplexAddress & {
        complex_name: string; dong: string; avg_price: number;
        avg_per_sqm: number; avg_area_m2: number; deal_count: number;
        build_year: number; last_deal_ym: string; score: number; reasons: string[];
      })[];
      report: string;
      error: string;
    }>("/recommendation/complexes", { method: "POST", body: JSON.stringify(params) }),

  simulation: (params: SimulationRequest) =>
    req("/simulation", { method: "POST", body: JSON.stringify(params) }),

  /** 최신 주담대 평균금리 (한국은행 ECOS) */
  marketRate: () =>
    req<{ rate: number; ym: string; source: string; is_live: boolean }>(
      "/simulation/market-rate"
    ),

  comparison: (listings: object[], recommendationResults?: object[]) =>
    req("/comparison", {
      method: "POST",
      body: JSON.stringify({ listings, recommendation_results: recommendationResults }),
    }),

  /** 시세추정·권리점검·상담을 합친 최근 활동 피드 */
  activity: (limit = 8) =>
    req<{ items: ActivityItem[] }>(`/activity?limit=${limit}`),

  history: (limit = 20, offset = 0, keyword = "") =>
    req<{ total: number; items: object[] }>(
      `/history?limit=${limit}&offset=${offset}&keyword=${encodeURIComponent(keyword)}`
    ),

  historyOne: (id: number) => req(`/history/${id}`),

  deleteHistory: (id: number) => req(`/history/${id}`, { method: "DELETE" }),

  deleteAllHistory: () => req("/history", { method: "DELETE" }),

  cases: () => req<{ items: PurchaseCase[] }>("/cases"),

  marketRegions: (params: { level?: "sido" | "sigungu" | "eup_myeon_dong" | "eupmyeondong" | "ri"; parent_code?: string } = {}) => {
    const query = new URLSearchParams();
    query.set("level", params.level ?? "sido");
    if (params.parent_code) query.set("parent_code", params.parent_code);
    return req<{ items: {
      code: string; parent_code: string | null; name: string; full_name: string;
      level: "sido" | "sigungu" | "eup_myeon_dong" | "eupmyeondong" | "ri"; lawd_code: string | null;
    }[] }>(`/market/regions?${query.toString()}`);
  },

  regionMarket: (params: { region_code: string; group_level?: "sigungu" | "eup_myeon_dong"; months?: number; property_type?: string; budget_max?: number }) => {
    const query = new URLSearchParams();
    query.set("region_code", params.region_code);
    if (params.group_level) query.set("group_level", params.group_level);
    query.set("months", String(params.months ?? 12));
    query.set("property_type", params.property_type ?? "all");
    if (params.budget_max) query.set("budget_max", String(params.budget_max));
    return req<{
      source: string; price_unit: "만원"; period: { from: string; to: string } | null;
      scope: { code: string; name: string; full_name: string; level: string } | null;
      property_type: string; items: {
        region_name: string; region_code: string; lawd_code: string; deal_count: number; avg_price: number;
        sample_size: number; median_price: number; price_q1: number; price_q3: number;
        avg_per_sqm: number; median_per_sqm: number; asset_count: number; last_deal_ym: string;
        budget_fit_count: number; budget_fit_ratio: number; confidence: "high" | "medium" | "low";
      }[];
    }>(`/market/regions/summary?${query.toString()}`);
  },

  createCase: (data: {
    title: string; budget_min?: number; budget_max?: number;
    target_regions?: string[]; notes?: string;
  }) => req<PurchaseCase>("/cases", { method: "POST", body: JSON.stringify(data) }),

  caseOne: (id: number) => req<PurchaseCase>(`/cases/${id}`),

  caseComparison: (id: number, propertyIds: number[]) => {
    const query = new URLSearchParams();
    propertyIds.forEach((propertyId) => query.append("property_id", String(propertyId)));
    return req<CaseCandidateComparison>(`/cases/${id}/comparison?${query.toString()}`);
  },

  selectCaseCandidate: (caseId: number, propertyId: number, reason: string) =>
    req<PurchaseCase>(`/cases/${caseId}/decision`, {
      method: "POST", body: JSON.stringify({ property_id: propertyId, reason }),
    }),

  caseExecution: (caseId: number) => req<CaseExecution>(`/cases/${caseId}/execution`),

  clearCaseDecision: (caseId: number) => req<PurchaseCase>(`/cases/${caseId}/decision`, { method: "DELETE" }),

  updateCaseExecution: (caseId: number, data: {
    contract_planned_date?: string | null; closing_planned_date?: string | null;
  }) => req<CaseExecution>(`/cases/${caseId}/execution`, { method: "PATCH", body: JSON.stringify(data) }),

  addExecutionTask: (caseId: number, data: {
    phase: ExecutionPhase; title: string; description?: string; actor_type?: ExecutionActor;
    required?: boolean; due_date?: string | null;
  }) => req(`/cases/${caseId}/execution/tasks`, { method: "POST", body: JSON.stringify(data) }),

  updateExecutionTask: (caseId: number, taskId: number, data: {
    status?: ExecutionTaskStatus; actor_type?: ExecutionActor; due_date?: string | null;
    checked_by?: string; outcome?: string; evidence_note?: string; follow_up?: string;
  }) => req(`/cases/${caseId}/execution/tasks/${taskId}`, { method: "PATCH", body: JSON.stringify(data) }),

  deleteExecutionTask: (caseId: number, taskId: number) =>
    req<void>(`/cases/${caseId}/execution/tasks/${taskId}`, { method: "DELETE" }),

  updateCase: (id: number, data: Partial<Pick<PurchaseCase,
    "title" | "status" | "budget_min" | "budget_max" | "target_regions" | "notes" | "buyer_profile"
  >>) => req<PurchaseCase>(`/cases/${id}`, { method: "PATCH", body: JSON.stringify(data) }),

  caseFundingScenarios: (caseId: number, data: {
    property_ids?: number[]; price_delta_won?: number; interest_delta_pct?: number; reserve_delta_won?: number;
  }) => req<import("@/lib/types").CaseFundingScenarioResult>(`/cases/${caseId}/funding-scenarios`, {
    method: "POST", body: JSON.stringify(data),
  }),
  caseRecommendations: (caseId:number,regionCode:string) => req<{results:import("@/lib/types").ComplexRecommendation[];error?:string}>(`/cases/${caseId}/recommendations?region_code=${encodeURIComponent(regionCode)}`),

  deleteCase: (id: number) => req<void>(`/cases/${id}`, { method: "DELETE" }),

  addCaseProperty: (caseId: number, data: {
    name: string; address?: string; category?: string; asking_price?: number;
    area_sqm?: number; notes?: string; history_id?: number;
    source?: "manual" | "recommendation" | "appraisal";
  }) => req<CaseProperty>(`/cases/${caseId}/properties`, { method: "POST", body: JSON.stringify(data) }),

  deleteCaseProperty: (caseId: number, propertyId: number) =>
    req<void>(`/cases/${caseId}/properties/${propertyId}`, { method: "DELETE" }),

  updateCaseProperty: (caseId: number, propertyId: number, data: {
    asking_price?: number | null;
    status?: "reviewing" | "shortlisted" | "rejected" | "selected"; notes?: string;
  }) => req(`/cases/${caseId}/properties/${propertyId}`, { method: "PATCH", body: JSON.stringify(data) }),

  applyListingUpdate: (caseId: number, propertyId: number, expectedRevisionId: number, expectedConfirmedAt: string) =>
    req<{ changed: boolean; invalidated_analyses: string[]; decision_reopened: boolean }>(
      `/cases/${caseId}/properties/${propertyId}/source-update`, {
        method: "POST", body: JSON.stringify({ expected_revision_id: expectedRevisionId,
                                                 expected_confirmed_at: expectedConfirmedAt }),
      }),

  updateCandidateChecklist: (caseId: number, propertyId: number, checklistId: number, data: {
    status: "todo" | "done" | "warning" | "blocked"; evidence?: string;
  }) => req(`/cases/${caseId}/properties/${propertyId}/checklist/${checklistId}`, {
    method: "PATCH", body: JSON.stringify(data),
  }),

  addCaseRegion: (caseId: number, data: {
    region_code: string; property_type: string; budget_max_won?: number;
    months?: number; source?: "market_explorer" | "concierge";
  }) => req(`/cases/${caseId}/regions`, { method: "POST", body: JSON.stringify(data) }),

  deleteCaseRegion: (caseId: number, regionId: number) =>
    req<void>(`/cases/${caseId}/regions/${regionId}`, { method: "DELETE" }),

  /** 등기부등본·건축물대장 PDF 권리관계 위험 점검 (PDF는 base64) */
  rightsAnalyze: (params: {
      case_id?: number;
      candidate_id?: number;
    registry_pdf_b64?: string;
    building_pdf_b64?: string;
    my_deposit?: number;
    market_price?: number;
  }) =>
    req<{
      error: string;
      disclaimer: string;
      risk_score: number;
      risk_grade: "safe" | "caution" | "danger";
      risk_label: string;
      reasons: string[];
      registry?: {
        error: string; address: string; owner: string; has_summary: boolean;
        critical: { keyword: string; description: string }[];
        warnings: { keyword: string; description: string }[];
        mortgage_total: number; mortgage_count: number;
        senior_deposits: number; senior_count: number;
      };
      building?: { error: string; violation: boolean; main_use: string; approval_date: string };
      deposit_safety?: {
        available: boolean; senior_total: number; total_burden: number;
        burden_ratio: number; grade: string; label: string;
        expected_auction: number; expected_recovery: number; recovery_shortfall: number;
        small_tenant: boolean;
        small_tenant_rule: { region: string; limit: number; priority_amount: number };
      };
    }>("/rights/analyze", { method: "POST", body: JSON.stringify(params) }),

  /** 부동산 법률·세금 AI 정보 안내 챗봇 */
  chat: (message: string, history: { role: string; content: string }[] = [], conversationId: string | null = null) =>
    conversationJob<{
      answer: string;
      sources: import("./types").ChatSource[];
      tool_used: string | null;
      disclaimer: string;
      conversation_id?: string;
    }>("/chat/jobs", { message, history, conversation_id: conversationId }),

  chatConversation: async (conversationId: string, signal?: AbortSignal) => {
    const response = await fetch(`${BASE}/chat/conversations/${encodeURIComponent(conversationId)}`, {
      credentials: "include", cache: "no-store", signal,
    });
    if (response.status === 404 || response.status === 422) return null;
    if (!response.ok) throw new Error("대화를 복원하지 못했습니다.");
    return response.json() as Promise<{
      conversation_id: string;
      messages: { role: "user" | "assistant"; content: string; sources?: import("./types").ChatSource[];
        tool?: string | null; disclaimer?: string }[];
    }>;
  },

  conciergeMessage: (message: string, conversationId: string | null, candidate?: { case_id?: number; candidate_id?: number; clear_context?: boolean }) =>
    conversationJob<ConciergeResponse>("/concierge/jobs", { message, conversation_id: conversationId, ...candidate }),

  addressSearch: (query: string, type: "keyword" | "address" = "keyword") =>
    req<{ documents: object[]; meta: object }>(
      `/address/search?query=${encodeURIComponent(query)}&type=${type}`
    ),
};
