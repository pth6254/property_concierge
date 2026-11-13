// 개발용 가상 매물(data/sample_listings.csv, 43건)로 동작하는 체험 도구를 운영 빌드에서 숨긴다.
// 실제 사용자가 가짜 매물을 실제 후보로 오인하지 않게 하기 위해서다. 개발 서버·CI(next dev)에서는 그대로 보이며,
// 운영 빌드에서도 보여야 하면 빌드 시 NEXT_PUBLIC_SAMPLE_TOOLS=1을 준다(NEXT_PUBLIC 값은 빌드에 고정된다).
export const SAMPLE_TOOLS = process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_SAMPLE_TOOLS === "1";
