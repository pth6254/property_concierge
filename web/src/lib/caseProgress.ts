import type { PurchaseCase } from "@/lib/types";

export type CaseStep = { key: string; label: string; done: boolean; href: string; action: string };

/**
 * 케이스의 작업 진행 단계. 케이스 화면 안내와 홈의 "이어서 하기"가 같은 기준을 쓴다.
 * 목록 응답처럼 후보 상세(properties)가 없으면 분석 완료 여부를 알 수 없으므로 완료로 보지 않는다.
 * 작업 진행 기준일 뿐 거래 안전·대출 승인과 무관하다.
 */
export function caseSteps(item: PurchaseCase): CaseStep[] {
  const properties = item.properties;
  const profile = item.buyer_profile;
  const conditionsReady = Boolean(item.budget_max && profile?.cash_available != null && profile?.monthly_payment_limit != null
    && profile?.loan_ratio != null && profile?.annual_interest_rate != null && profile?.loan_years != null
    && profile?.owned_homes != null && profile?.adjusted_area != null);
  const hasCandidates = (properties?.length ?? item.property_count) > 0;
  const analysesReady = Boolean(properties?.some(p => p.analyses.some(a => a.analysis_type === "appraisal" && a.status === "completed")
    && p.analyses.some(a => a.analysis_type === "simulation" && a.status === "completed")));
  return [
    { key: "conditions", label: "매수 조건 입력", done: conditionsReady, href: `/cases/${item.id}#buyer-profile`, action: "예산·보유 현금·월 상환 한도를 저장하세요." },
    { key: "explore", label: "동네 탐색", done: Boolean(item.regions?.length), href: `/explore?case_id=${item.id}`, action: "같은 면적·연식 조건으로 관심 동네를 비교하세요." },
    { key: "candidates", label: "후보 등록", done: hasCandidates, href: `/listings?case_id=${item.id}`, action: "확인한 매물의 주소·면적·희망가를 등록하세요." },
    { key: "analysis", label: "시세·자금 분석", done: analysesReady, href: `/cases/${item.id}#candidates`, action: "후보 카드에서 시세·자금 분석을 진행하세요." },
    { key: "comparison", label: "후보 비교", done: Boolean(item.selected_property_id), href: `/cases/${item.id}/comparison`, action: "분석 근거와 미확인 위험을 비교하고 선호 후보를 선택하세요." },
    { key: "execution", label: "거래 준비", done: false, href: `/cases/${item.id}/execution`, action: "현장·서류·대출 확인을 거래 준비 화면에 기록하세요." },
  ];
}

/**
 * 다음에 할 단계. 동네 탐색은 선택 단계라 후보가 이미 있으면 건너뛴다.
 * 최종 선택 이후에는 앞 단계가 비어 있어도 거래 준비를 안내한다.
 */
export function nextCaseStep(item: PurchaseCase): CaseStep {
  const steps = caseSteps(item);
  if (item.selected_property_id) return steps[steps.length - 1];
  const hasCandidates = steps.find(step => step.key === "candidates")!.done;
  return steps.find(step => !step.done && !(step.key === "explore" && hasCandidates)) ?? steps[steps.length - 1];
}
