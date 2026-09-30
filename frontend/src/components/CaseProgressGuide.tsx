import Link from "next/link";
import type { PurchaseCase } from "@/lib/types";

export default function CaseProgressGuide({item}:{item:PurchaseCase}) {
  const properties=item.properties??[];
  const profile=item.buyer_profile;
  const conditionsReady=Boolean(item.budget_max && profile?.cash_available!=null && profile?.monthly_payment_limit!=null
    && profile?.loan_ratio!=null && profile?.annual_interest_rate!=null && profile?.loan_years!=null
    && profile?.owned_homes!=null && profile?.adjusted_area!=null);
  const analysesReady=properties.length>0 && properties.some(p=>p.analyses.some(a=>a.analysis_type==="appraisal"&&a.status==="completed")&&p.analyses.some(a=>a.analysis_type==="simulation"&&a.status==="completed"));
  const steps=[
    {label:"매수 조건 입력",done:conditionsReady,href:`/cases/${item.id}#buyer-profile`,action:"예산·보유 현금·월 상환 한도를 저장하세요."},
    {label:"동네 탐색",done:Boolean(item.regions?.length),href:`/explore?case_id=${item.id}`,action:"같은 면적·연식 조건으로 관심 동네를 비교하세요."},
    {label:"후보 등록",done:properties.length>0,href:`/listings?case_id=${item.id}`,action:"확인한 매물의 주소·면적·희망가를 등록하세요."},
    {label:"시세·자금 분석",done:analysesReady,href:`/cases/${item.id}#candidates`,action:"후보 카드에서 시세·자금 분석을 진행하세요."},
    {label:"후보 비교",done:Boolean(item.selected_property_id),href:`/cases/${item.id}/comparison`,action:"분석 근거와 미확인 위험을 비교하고 선호 후보를 선택하세요."},
    {label:"거래 준비",done:false,href:`/cases/${item.id}/execution`,action:"현장·서류·대출 확인을 거래 준비 화면에 기록하세요."},
  ];
  const next=steps.find(step=>!step.done)!;
  return <section aria-label="매수 검토 진행 안내" className="rounded-xl border bg-emerald-50 p-4">
    <h2 className="font-bold">다음 단계: {next.label}</h2><p className="mt-1 text-sm">{next.action}</p>
    <ol className="mt-3 grid gap-2 sm:grid-cols-3">{steps.map((step,i)=><li key={step.label}><Link href={step.href} className="block rounded border bg-white p-3 text-sm">{step.done?"✓":i+1}. {step.label}</Link></li>)}</ol>
    <p className="mt-2 text-xs text-slate-600">이 안내는 작업 진행 기준입니다. 분석 완료·후보 선택이 거래 안전이나 대출 승인을 보장하지 않습니다.</p>
  </section>;
}
