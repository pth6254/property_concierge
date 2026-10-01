import type { BuyerProfile, CaseProperty, SimulationRequest } from "@/lib/types";

export type CandidateSimulationSeed = {
  asking_price: number | null;
  property_type: string;
  case_id: number;
  candidate_id: number;
  inputs: Partial<SimulationRequest>;
  profile_inputs: Partial<SimulationRequest>;
  input_source: "saved" | "profile";
  home_count_basis?: "after_purchase";
};

export function candidateSimulationSeed(property: CaseProperty, caseId: number, profile?: BuyerProfile): CandidateSimulationSeed {
  const profileInputs: Partial<SimulationRequest> = {
    // 저장된 분석의 현금은 이미 비상자금을 제외했으므로 공통 조건에서만 차감한다.
    cash_available: profile?.cash_available != null ? profile.cash_available - profile.emergency_reserve : undefined,
    monthly_payment_limit: profile?.monthly_payment_limit ?? undefined,
    annual_income: profile?.annual_income ?? undefined,
    existing_loan_annual_payment: profile?.existing_loan_annual_payment,
    loan_ratio: profile?.loan_ratio ?? undefined,
    annual_interest_rate: profile?.annual_interest_rate ?? undefined,
    loan_years: profile?.loan_years ?? undefined,
    owned_homes: profile?.owned_homes ?? undefined,
    adjusted_area: profile?.adjusted_area ?? undefined,
  };
  const analysis = property.analyses.find(analysis => analysis.analysis_type === "simulation");
  const saved = analysis?.summary.inputs;
  const savedInputs = saved !== null && typeof saved === "object" && !Array.isArray(saved)
    ? Object.fromEntries(Object.entries(saved).filter(([, value]) => value !== null && value !== undefined))
    : {};
  return {
    asking_price: property.asking_price, property_type: property.category,
    case_id: caseId, candidate_id: property.id,
    inputs: { ...profileInputs, ...savedInputs }, profile_inputs: profileInputs,
    input_source: Object.keys(savedInputs).length > 0 ? "saved" : "profile",
    home_count_basis: analysis?.summary.home_count_basis === "after_purchase" ? "after_purchase" : undefined,
  };
}
