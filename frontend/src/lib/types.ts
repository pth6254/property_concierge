// TypeScript types mirroring Pydantic schemas

export interface ComparableTransaction {
  complex_name?: string;
  address?: string;
  area_m2?: number;
  deal_price?: number;
  deal_date?: string;
  price_per_m2?: number;
  source?: string;
  match_level?: string;
}

export interface AppraisalResult {
  estimated_price?: number;
  low_price?: number;
  high_price?: number;
  asking_price?: number;
  gap_rate?: number;
  judgement: string;
  confidence: number;
  comparables: ComparableTransaction[];
  warnings: string[];
  data_source: string[];
  raw?: Record<string, unknown>;
}

export interface PropertyListing {
  listing_id: string;
  complex_name?: string;
  address: string;
  region?: string;
  property_type: string;
  area_m2?: number;
  asking_price: number;
  floor?: number;
  built_year?: number;
  lat?: number;
  lng?: number;
  station_distance_m?: number;
  school_distance_m?: number;
  deposit_price?: number;
  maintenance_fee?: number;
  description?: string;
}

export interface RecommendationResult {
  listing: PropertyListing;
  total_score: number;
  price_score?: number;
  location_score?: number;
  investment_score?: number;
  risk_score?: number;
  recommendation_label?: string;
  reasons?: string[];
  risks?: string[];
}

export interface AcquisitionCost {
  acquisition_tax: number;
  brokerage_fee: number;
  other_cost: number;
  total: number;
}

export interface LoanSummary {
  monthly_payment: number;
  total_repayment: number;
  total_interest: number;
}

export interface CashFlowSummary {
  monthly_rental_income: number;
  monthly_loan_payment: number;
  monthly_management_fee: number;
  monthly_net: number;
}

export interface ScenarioResult {
  annual_growth_rate: number;
  expected_sale_price: number;
  capital_gain: number;
  total_rental_income: number;
  net_profit: number;              // 세후
  equity_roi: number;
  annual_equity_roi: number;
  rental_yield: number;
  pre_tax_profit: number;
  capital_gains_tax: number;
  holding_tax_total: number;
  sale_brokerage_fee: number;
  cgt_note: string;
  infinite_leverage: boolean;
}

export interface FinanceCheck {
  ltv: number;
  ltv_limit: number;
  ltv_exceeded: boolean;
  ltv_max_loan: number;
  dsr?: number;
  dsr_limit: number;
  dsr_exceeded: boolean;
  stress_rate?: number;
  dsr_annual_payment?: number;
  dsr_max_loan?: number;
}

export interface RateSensitivityCell {
  growth_rate: number;
  interest_rate: number;
  annual_equity_roi: number;
  net_profit: number;
}

export interface SimulationResult {
  purchase_price: number;
  loan_amount: number;
  equity: number;
  required_cash: number;
  acquisition_cost: AcquisitionCost;
  loan: LoanSummary;
  cash_flow: CashFlowSummary;
  scenario_base: ScenarioResult;
  scenario_bull: ScenarioResult;
  scenario_bear: ScenarioResult;
  tax_rules_as_of: string;
  official_price_used: number;
  official_price_estimated: boolean;
  finance_check?: FinanceCheck;
  breakeven_growth_rate?: number;
  rate_sensitivity: RateSensitivityCell[];
}

export interface PropertyComparisonRow {
  rank: number;
  is_winner: boolean;
  listing: PropertyListing;
  total_score?: number;
  highlights?: string[];
  warnings?: string[];
  simulation_result?: SimulationResult;
}

export interface ComparisonResult {
  rows: PropertyComparisonRow[];
  decision_report?: string;
}

export interface HistoryItem {
  id: number;
  query: string;
  category: string;
  created: string;
  estimated_value?: number;
  valuation_verdict?: string;
  investment_grade?: string;
  cap_rate?: number;
}

/** 홈 '최근 활동' 통합 피드 항목 (시세추정 + 권리점검 + 상담) */
export interface ActivityItem {
  type: "appraisal" | "rights" | "chat";
  id: number;
  title: string;
  subtitle: string;
  created: string;
  // appraisal
  estimated_value?: number;
  valuation_verdict?: string;
  investment_grade?: string;
  // rights
  risk_grade?: "safe" | "caution" | "danger";
  risk_score?: number;
  // chat
  tool_used?: string | null;
}

export type PurchaseCaseStatus = "exploring" | "reviewing" | "negotiating" | "decided" | "archived";

export interface CaseAppraisalSummary {
  history_id: number;
  query: string;
  estimated_value: number | null;
  valuation_verdict: string | null;
  created: string;
}

export interface CaseProperty {
  next_actions?: CandidateNextAction[];
  id: number;
  case_id: number;
  name: string;
  address: string;
  category: string;
  asking_price: number | null;
  area_sqm: number | null;
  legal_region_code: string | null;
  source: "manual" | "recommendation" | "appraisal";
  source_listing_id: number | null;
  source_status: ListingSourceStatus | null;
  source_reviews: {
    id: number; created: string; previous_snapshot: Record<string, unknown>;
    applied_snapshot: Record<string, unknown>;
    previous_decision: { reason: string; decided_at: string | null } | null;
    invalidated_analyses: string[];
    previous_analyses: { type: string; status: string; summary: Record<string, unknown>; analyzed_at: string | null }[];
    previous_execution: { title: string; status: string; outcome: string; evidence_note: string }[];
  }[];
  status: "reviewing" | "shortlisted" | "rejected" | "selected";
  notes: string;
  history_id: number | null;
    appraisal: CaseAppraisalSummary | null;
    analyses: CandidateAnalysis[];
    checklist: CandidateChecklistItem[];
    review_progress: number;
  created: string;
  updated: string;
}

export interface ListingSourceStatus {
  status: "current" | "changed" | "needs_confirmation" | "missing";
  listing_id: number;
  needs_confirmation: boolean;
  changes: Record<string, { saved: unknown; current: unknown }>;
  saved: Record<string, unknown>;
  current: (Record<string, unknown> & { revision_id?: number; confirmed_at?: string }) | null;
}

export interface CandidateNextAction {
  code: string;
  title: string;
  reason: string;
  target: "price" | "appraisal" | "simulation" | "rights" | "checklist";
  priority: "warning" | "input" | "normal";
  checklist_id: number | null;
}

export interface CandidateAnalysis {
  id: number;
  analysis_type: "appraisal" | "simulation" | "rights";
  reference_id: number | null;
  status: "pending" | "completed" | "failed" | "stale";
  summary: Record<string, unknown>;
  analyzed_at: string | null;
  expires_at: string | null;
  days_remaining: number | null;
  updated: string;
}

export interface CandidateChecklistItem {
  id: number;
  category: "price" | "funding" | "rights" | "site" | "contract";
  title: string;
  status: "todo" | "done" | "warning" | "blocked";
  source: string;
  evidence: string;
  sort_order: number;
  completed_at: string | null;
  updated: string;
}

export interface CaseRegion {
  id: number;
  case_id: number;
  region_code: string;
  region_name: string;
  source: "market_explorer" | "concierge";
  property_type: string;
  budget_max_won: number | null;
  period_from: string | null;
  period_to: string | null;
  stats_snapshot: ConciergeRegionItem;
  created: string;
}

export interface PurchaseCase {
  id: number;
  title: string;
  status: PurchaseCaseStatus;
  purpose: "purchase";
  budget_min: number | null;
  budget_max: number | null;
  buyer_profile: BuyerProfile;
  target_regions: string[];
  notes: string;
  created: string;
  updated: string;
  property_count: number;
  selected_property_id: number | null;
  decision_reason: string;
  decided_at: string | null;
  properties?: CaseProperty[];
  regions?: CaseRegion[];
  workspace?: {
    checklist_total: number;
    checklist_done: number;
    warning_count: number;
    blocked_count: number;
    progress_percent: number;
  };
}

export interface BuyerProfile {
  cash_available: number | null; emergency_reserve: number;
  monthly_payment_limit: number | null; annual_income: number | null;
  existing_loan_annual_payment: number; loan_ratio: number | null;
  annual_interest_rate: number | null; loan_years: number | null;
  owned_homes: number | null; adjusted_area: boolean | null;
  min_area_sqm: number | null; min_build_year: number | null;
  property_types: string[]; priority: "cash" | "monthly" | "value" | "liquidity" | "age";
}

export interface CaseFundingScenarioResult {
  case_id: number; persisted: false;
  scenario_inputs: { price_delta_won: number; interest_delta_pct: number; reserve_delta_won: number };
  rows: { property_id: number; name: string; asking_price: number | null; source_status: string | null;
    baseline: { status: string; missing?: string[]; summary?: Record<string, unknown>; warnings?: string[] };
    scenario: { status: string; missing?: string[]; summary?: Record<string, unknown>; warnings?: string[] };
    deltas: Record<string, number | null> }[];
}

export interface ComplexRecommendation {
  complex_name:string; dong:string; avg_price:number; avg_per_sqm:number;
  avg_area_m2:number; deal_count:number; build_year:number; last_deal_ym:string;
  score:number; reasons:string[]; score_factors?:Record<string,number>;
  score_weights?:Record<string,number>;
  road_address?:string|null;jibun_address?:string|null;
}

export interface CaseCandidateComparisonRow {
  property_id: number;
  name: string;
  address: string;
  status: CaseProperty["status"];
  asking_price: number | null;
  area_sqm: number | null;
  estimated_value: number | null;
  appraisal_confidence: number | null;
  appraisal_match_level: string | null;
  appraisal_comparable_count: number | null;
  source_status: ListingSourceStatus | null;
  price_gap: number | null;
  price_gap_ratio: number | null;
  funding: Record<string, unknown> | null;
  rights: Record<string, unknown> | null;
  analysis_status: Record<"appraisal" | "simulation" | "rights", "completed" | "stale" | "missing" | "pending" | "failed">;
  review_progress: number;
  review_stage: "exploration" | "comparison" | "detailed" | "precontract" | "excluded";
  missing: string[];
  warnings: string[];
  highlights: string[];
  decision_ready: boolean;
}

export interface CaseCandidateComparison {
  case_id: number;
  case_title: string;
  budget_min: number | null;
  budget_max: number | null;
  selected_property_id: number | null;
  decision_reason: string;
  decided_at: string | null;
  rows: CaseCandidateComparisonRow[];
}

export type ExecutionPhase = "before_contract" | "before_closing" | "closing_day" | "after_closing";
export type ExecutionTaskStatus = "scheduled" | "in_progress" | "waiting_external" | "done" | "problem" | "not_applicable";
export type ExecutionActor = "self" | "bank" | "broker" | "legal_agent" | "tax_agent" | "other";

export interface CaseExecutionTask {
  id: number;
  plan_id: number;
  phase: ExecutionPhase;
  template_key: string | null;
  title: string;
  description: string;
  actor_type: ExecutionActor;
  status: ExecutionTaskStatus;
  required: boolean;
  due_date: string | null;
  overdue: boolean;
  completed_at: string | null;
  checked_by: string;
  outcome: string;
  evidence_note: string;
  follow_up: string;
  source: "system" | "user";
  sort_order: number;
  created: string;
  updated: string;
}

export interface CaseExecution {
  case_id: number;
  requires_selection: boolean;
  plan: {
    id: number;
    property_id: number | null;
    contract_planned_date: string | null;
    closing_planned_date: string | null;
    status: string;
    created: string;
    updated: string;
  } | null;
  tasks: CaseExecutionTask[];
  summary: {
    progress_percent: number;
    total: number;
    done: number;
    overdue: number;
    problems: number;
    waiting_external: number;
    blockers: { task_id: number; title: string; reason: string }[];
  };
}

export type ConciergeIntent =
  | "find_region" | "select_property" | "search_listing" | "appraise" | "compare"
  | "simulate" | "rights_check" | "tax_legal" | "general";

export interface ConciergeCriteria {
  property_type: string | null;
  transaction_type: "purchase" | "rent" | "lease" | null;
  budget_max_won: number | null;
  region_name: string | null;
  region_code: string | null;
  area_min_sqm: number | null;
  purpose: "residence" | "investment" | null;
}

export interface ConciergeRegionItem {
  region_name: string;
  region_code: string;
  lawd_code: string;
  deal_count: number;
  sample_size: number;
  avg_price: number;
  median_price: number;
  price_q1: number;
  price_q3: number;
  avg_per_sqm: number;
  median_per_sqm: number;
  asset_count: number;
  last_deal_ym: string;
  budget_fit_count: number;
  budget_fit_ratio: number;
  confidence: "high" | "medium" | "low";
}

export interface ChatSource {
  title: string;
  source: string;
  url?: string;
  effective_date?: string;
  collected_at?: string;
  origin?: string;
}

export interface ComplexAddress {
  complex_id?: number;
  road_address?: string;
  jibun_address?: string;
  address_status?: "matched" | "unresolved" | "ambiguous" | "unavailable";
  address_source?: string;
  address_checked_at?: string | null;
}

export interface ConciergeComplex extends ComplexAddress {
  complex_name: string;
  dong: string;
  avg_price: number;
  avg_area_m2: number;
  deal_count: number;
}

export interface ConciergeResponse {
  conversation_id: string;
  status: "completed" | "needs_input" | "not_available" | "error" | "queued";
  intent: ConciergeIntent;
  answer: string;
  criteria: ConciergeCriteria;
  data: {
    results?: ConciergeComplex[];
    region_name?: string;
    result_url?: string;
    comparison?: CaseCandidateComparison;
    funding_inputs?: Partial<SimulationRequest>;
    candidate_funding?: { required_cash?: number; monthly_payment?: number; cash_shortfall?: number };
    sources?: ChatSource[];
    disclaimer?: string;
    job_id?: string;
    case_id?: number;
    candidate_id?: number;
    candidate_name?: string;
    input_url?: string;
    source?: string;
    price_unit?: string;
    period?: { from: string; to: string } | null;
    items?: ConciergeRegionItem[];
    region_candidates?: { code: string; full_name: string; level: string }[];
  };
  missing_fields: string[];
  tool_used: string | null;
  pending_action: Record<string, unknown> | null;
}

// Request types
export interface RecommendationRequest {
  region?: string;
  property_type?: string;
  budget_min?: number;
  budget_max?: number;
  area_m2?: number;
  purpose?: string;
  limit?: number;
}

export interface SimulationRequest {
  cash_available?: number;
  monthly_payment_limit?: number;
  case_id?: number;
  candidate_id?: number;
  purchase_price: number;
  loan_ratio: number;
  annual_interest_rate: number;
  loan_years: number;
  repayment_type: "equal_payment" | "equal_principal" | "interest_only";
  holding_years: number;
  expected_annual_growth_rate: number;
  rent_deposit?: number;
  rent_fee?: number;
  monthly_management_fee?: number;
  property_type: string;
  owned_homes: number;
  official_price?: number;
  residence_years?: number;
  vacancy_rate?: number;
  adjusted_area?: boolean;
  annual_income?: number;
  existing_loan_annual_payment?: number;
}
