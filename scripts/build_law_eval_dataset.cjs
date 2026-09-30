// 수집한 공식 원문에서 조문 식별자를 확인한 뒤 검색 평가 정답을 생성한다.
const fs = require("fs");
const crypto = require("crypto");
const specs = [
  ["001248", "3", "전입신고와 주택 인도를 마친 세입자의 대항력은 어느 조문에서 확인하나요?"],
  ["001248", "3:2", "주택 보증금을 경매에서 회수하는 우선변제권의 근거 조문을 찾아줘"],
  ["001248", "3:3", "주택 보증금을 돌려받지 못하고 이사해야 해요. 임차권등기명령 신청 근거를 찾아줘"],
  ["001248", "3:6", "주택 임대차 확정일자 부여와 임대차 정보 제공 관련 조문은?"],
  ["001248", "3:7", "주택 계약 전에 임대인이 제시해야 하는 정보의 근거를 찾아줘"],
  ["001248", "4", "주택 임대차기간과 보증금 반환 전 계약 존속 관련 조문을 찾아줘"],
  ["001248", "6", "주택 임대차 계약의 묵시적 갱신 관련 근거를 찾아줘"],
  ["001248", "6:2", "묵시적으로 갱신된 주택 계약을 세입자가 해지하는 근거 조문은?"],
  ["001248", "6:3", "주택 세입자의 계약갱신 요구권 조문을 찾아줘"],
  ["001248", "7", "주택 임대료 증액 청구 제한은 어느 조문에 있나요?"],
  ["001248", "7:2", "주택 전세보증금을 월세로 전환할 때 산정률 제한 관련 조문은?"],
  ["001248", "8", "주택 소액임차인 보증금 중 일정액 보호 근거를 찾아줘"],
  ["001654", "25", "공인중개사의 중개대상물 확인 설명 의무 근거를 찾아줘"],
  ["001654", "26", "공인중개사가 거래계약서를 작성하고 보관해야 하는 근거 조문은?"],
  ["001654", "30", "중개사가 손해배상 책임을 보장하는 보증보험 관련 근거를 찾아줘"],
  ["001654", "32", "공인중개사 중개보수와 실비 관련 조문을 찾아줘"],
  ["001654", "33", "개업공인중개사의 금지행위 관련 근거 조문을 찾아줘"],
  ["001654", "18:2", "공인중개사가 인터넷에 중개대상물을 표시 광고할 때 준수할 조문은?"],
  ["009276", "3", "상가 세입자의 대항력 관련 조문을 찾아줘"],
  ["009276", "5", "상가 보증금 회수와 우선변제권 근거 조문은?"],
  ["009276", "6", "상가 보증금을 돌려받지 못했을 때 임차권등기명령 근거를 찾아줘"],
  ["009276", "10", "상가 임대차 계약갱신 요구 관련 조문을 찾아줘"],
  ["009276", "10:4", "상가 임차인의 권리금 회수기회 보호 근거 조문은?"],
  ["012480", "3", "부동산 매매 계약 거래신고 의무 근거 조문을 찾아줘"],
  ["012480", "3:2", "부동산 거래 계약을 해제했을 때 신고하는 근거 조문은?"],
  ["012480", "6:2", "주택 임대차 계약 신고 의무 근거 조문을 찾아줘"],
  ["012480", "11", "토지거래허가구역 안에서 계약 허가 관련 조문을 찾아줘"],
  ["001178", "3", "부동산 실권리자 명의 등기 의무 근거를 찾아줘"],
  ["001178", "4", "부동산 명의신탁약정의 효력 관련 조문을 찾아줘"],
];
const laws = new Map();
for (const directory of fs.readdirSync("data/law_corpus")) {
  const path = `data/law_corpus/${directory}/law.json`;
  if (fs.existsSync(path)) { const raw=fs.readFileSync(path,"utf8"); const law=JSON.parse(raw); laws.set(law.law_id,{law,hash:crypto.createHash("sha256").update(raw).digest("hex")}); }
}
const cases = specs.map(([lawId, article, question],i)=> {
  const {law,hash}=laws.get(lawId) ?? {};
  const [number,branch=""]=article.split(":");
  if (!law?.articles.some(a=>a.number===number && a.branch_number===branch && a.is_article==="조문")) throw Error(`원문 조문 없음: ${lawId}:${article}`);
  return {id:`official-law-${i+1}`,question,relevant_articles:[{law_id:lawId,article:`제${number}조${branch?"의"+branch:""}`}],
    require_official_law:true,reference:{basis:"official_reference",source:law.source_url,as_of:law.collected_at.slice(0,10),
      explanation:`${law.law_name}의 수집 원문에서 조문 존재 확인. SHA256 ${hash}. 의미적 정답의 독립 전문가 검토는 미완료.`,independently_verified:false}};
});
cases.push({id:"official-out-of-domain",question:"파이썬 딕셔너리 정렬 코드 알려줘",expect_no_results:true,require_official_law:true});
fs.writeFileSync("evaluation/datasets/law-rag.json",JSON.stringify({version:"1.0",suite:"rag",cases},null,2)+"\n");
console.log(`공식 원문 기반 ${cases.length}개 검색 정답 생성`);
