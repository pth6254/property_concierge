import type { Metadata } from "next";

export const metadata: Metadata = { title: "이용약관 — 부동산 컨시어지" };

const SECTIONS = [
  {
    title: "1. 서비스의 성격",
    body: [
      "본 서비스는 AI 기반 참고용 부동산 정보 분석 도구입니다.",
      "시세추정은 자동가치산정(AVM) 기반 참고 자료이며, 「감정평가 및 감정평가사에 관한 법률」에 따른 감정평가가 아닙니다.",
      "권리관계 점검·법률·세금 안내는 일반 정보 제공이며 법률사무(권리분석·법률상담)나 세무 대리가 아닙니다. 계약·투자·세무 결정 전 반드시 감정평가사·법무사·변호사·세무사 등 전문가의 확인을 받으시기 바랍니다.",
    ],
  },
  {
    title: "2. 계정",
    body: [
      "1인 1계정을 원칙으로 하며, 계정 정보는 본인이 안전하게 관리해야 합니다.",
      "회원 탈퇴 시 계정과 이용 기록은 즉시 삭제되며 복구할 수 없습니다.",
    ],
  },
  {
    title: "3. 금지 행위",
    body: [
      "자동화 도구를 이용한 대량 요청, 서비스 역설계, 분석 결과의 무단 상업적 재배포.",
      "타인의 개인정보(등기부등본 등)를 권한 없이 업로드하는 행위.",
      "남용 방지를 위해 기능별 요청 횟수가 제한될 수 있습니다.",
    ],
  },
  {
    title: "4. 책임의 한계",
    body: [
      "분석 결과의 정확성·완전성은 보장되지 않으며, 분석 결과에 근거한 의사결정의 책임은 이용자에게 있습니다.",
      "실거래가 등 외부 데이터 출처의 오류·지연으로 인한 손해에 대해 서비스는 책임지지 않습니다.",
    ],
  },
  {
    title: "5. 약관의 변경",
    body: [
      "약관 변경 시 본 페이지에 게시하며, 게시 후 계속 이용하면 변경에 동의한 것으로 봅니다.",
    ],
  },
];

export default function TermsPage() {
  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-extrabold tracking-tight text-ink mb-1">이용약관</h1>
      <p className="text-xs text-ink-faint mb-6">시행일: 2026년 7월 11일</p>
      <div className="space-y-5">
        {SECTIONS.map(s => (
          <section key={s.title} className="rounded-xl border border-line bg-surface p-5">
            <h2 className="text-sm font-bold text-ink mb-2">{s.title}</h2>
            <ul className="list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-ink-muted">
              {s.body.map((line, i) => <li key={i}>{line}</li>)}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
