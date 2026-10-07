export type IncomeValuationInput = {
  monthly_rent_won: number;
  monthly_operating_cost_min_won: number | null;
  monthly_operating_cost_max_won: number | null;
  cap_rate_min_pct: number;
  cap_rate_max_pct: number;
  asking_price_won: number | null;
  valuation_unit: "single_unit" | "whole_building";
  as_of_date: string;
};

export type IncomeScenario = {
  result_kind: "conditional_scenario" | "withheld";
  inputs: IncomeValuationInput;
  annual_rent_won: number;
  annual_noi_min_won: number | null;
  annual_noi_max_won: number | null;
  gross_yield_pct: number | null;
  net_yield_min_pct: number | null;
  net_yield_max_pct: number | null;
  low_price_won: number | null;
  high_price_won: number | null;
  scenarios: { cap_rate_pct: number; low_price_won: number; high_price_won: number }[];
  limitations: string[];
  calculation_version: string;
};

export type LandInformation = {
  schema_version: string; result_kind: "public_reference";
  pnu: string; address: string; road_address: string;
  scope: "single_parcel"; requested_as_of: string; checked_at: string;
  status: "found" | "partial" | "unavailable";
  fields: {
    land_area_sqm: number | null; land_category: string | null;
    actual_use: string | null; terrain_height: string | null; terrain_shape: string | null;
    road_frontage: string | null; zone_primary: string | null; zone_secondary: string | null;
    official_price_won_per_sqm: number | null;
  };
  official_reference_total_won: number | null; official_reference_area_sqm: number | null;
  characteristics_year: string | null; official_price_year: string | null;
  land_use: { name: string | null; conflict: string | null; record_updated_at: string | null }[];
  sources: { id: string; title: string; url: string; status: string; checked_at: string; reference_year: string | null; record_updated_at: string | null }[];
  missing_fields: string[]; limitations: string[];
};

export type ValuationSupportResult = {
  support_version: string; agent_name: string; address: string; as_of_date: string;
  valuation_method: string; limitations: string[];
  income_scenario?: IncomeScenario; land_information?: LandInformation;
  valuation?: ValuationAssessment;
};

export type ValuationContext = {
  scope: "single_unit" | "whole_building" | "land_and_building" | "single_parcel" | "unknown";
  area_basis: "exclusive" | "supply" | "gross" | "land" | "unknown";
  transaction_type: "sale" | "jeonse" | "rent" | "unknown";
  dong: string; ho: string;
};
export type ValuationAssessment = {
  schema_version: string; policy_version: string; input_fingerprint: string;
  subject: ValuationContext & { category: string; subtype: string; address: string; building_name: string; area_sqm: number | null; as_of_date: string; purpose: string; identity_level: string };
  result_kind: "market_reference" | "conditional_scenario" | "public_reference" | "partial_reference" | "withheld" | "unsupported";
  comparison_eligible: boolean; model_status: string; interval_basis: string;
  checks: { code: string; status: string; message: string; source: string; reference_date: string | null; observed_at: string | null }[];
  methods: { method: string; status: string; reason: string; engine_version: string | null }[];
  next_actions: string[]; limitations: string[];
};
