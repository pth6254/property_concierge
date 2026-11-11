import type { CaseProperty } from "@/lib/types";

/** 권리 점검 화면에 후보를 넘기는 값. 시세 분석이 있으면 추정가, 없으면 희망가를 기준 금액으로 쓴다. */
export function candidateRightsSeed(property: CaseProperty, caseId: number) {
  return {
    market_price: property.appraisal?.estimated_value ?? property.asking_price,
    address: property.address, case_id: caseId, candidate_id: property.id,
  };
}
