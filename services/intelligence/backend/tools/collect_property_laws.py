"""국가법령정보센터 현행 법령을 요약 코퍼스와 분리해 원문·조문 파일로 수집한다."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

from concierge_workspace import REPO_ROOT
ROOT = REPO_ROOT
BASE = "https://www.law.go.kr/DRF"
DEFAULT_LAWS = [
    "주택임대차보호법", "주택임대차보호법 시행령",
    "상가건물 임대차보호법", "상가건물 임대차보호법 시행령",
    "공인중개사법", "공인중개사법 시행령",
    "부동산 거래신고 등에 관한 법률", "부동산 거래신고 등에 관한 법률 시행령",
    "부동산등기법", "부동산등기규칙",
    "부동산 실권리자명의 등기에 관한 법률", "부동산 실권리자명의 등기에 관한 법률 시행령",
    "주택법", "주택법 시행령", "건축법", "건축법 시행령",
    "국토의 계획 및 이용에 관한 법률", "국토의 계획 및 이용에 관한 법률 시행령",
    "도시 및 주거환경정비법", "도시 및 주거환경정비법 시행령",
    "집합건물의 소유 및 관리에 관한 법률", "집합건물의 소유 및 관리에 관한 법률 시행령",
    "부동산 가격공시에 관한 법률", "부동산 가격공시에 관한 법률 시행령",
]


def as_list(value):
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def clean_text(value) -> str:
    if isinstance(value, list):
        return "\n".join(filter(None, (clean_text(item) for item in value)))
    if isinstance(value, dict):
        return clean_text(value.get("#text", ""))
    return html.unescape(re.sub(r"<[^>]+>", "", str(value or ""))).strip()


def provision_text(node: dict) -> str:
    # 항뿐 아니라 호·목까지 순서대로 보존하고 길이로 자르지 않는다.
    parts = [clean_text(node.get(key)) for key in ("조문내용", "항내용", "호내용", "목내용")]
    for key in ("항", "호", "목"):
        parts.extend(provision_text(child) for child in as_list(node.get(key)))
    return "\n".join(part for part in parts if part)


def redact_auth(value):
    """API 응답에 인증값 포함 링크가 있어도 파일로 유출되지 않게 한다."""
    if isinstance(value, dict):
        return {key: redact_auth(item) for key, item in value.items() if key.upper() != "OC"}
    if isinstance(value, list):
        return [redact_auth(item) for item in value]
    if isinstance(value, str):
        return re.sub(r"([?&](?:amp;)?OC=)[^&\s\"'<>]+", r"\1REDACTED", value, flags=re.I)
    return value


def normalize_law(payload: dict, match: dict, collected_at: str) -> dict:
    body = payload.get("법령")
    if not isinstance(body, dict) or not isinstance(body.get("기본정보"), dict):
        raise ValueError("법령 기본정보가 없는 응답")
    info = body["기본정보"]
    name = clean_text(info.get("법령명_한글"))
    if re.sub(r"\s", "", name) != re.sub(r"\s", "", match["법령명한글"]):
        raise ValueError("검색 법령과 본문 법령 불일치")
    effective = clean_text(info.get("시행일자"))
    if not re.fullmatch(r"\d{8}", effective):
        raise ValueError("시행일 확인 불가")
    if effective > collected_at[:10].replace("-", ""):
        raise ValueError("시행예정 법령은 현행 수집에서 제외")
    articles = []
    for article in as_list((body.get("조문") or {}).get("조문단위")):
        text = provision_text(article)
        if not text:
            continue
        articles.append({
            "number": clean_text(article.get("조문번호")),
            "branch_number": clean_text(article.get("조문가지번호")),
            "title": clean_text(article.get("조문제목")),
            "is_article": clean_text(article.get("조문여부")),
            "effective_date": clean_text(article.get("조문시행일자")),
            "text": text,
        })
    if not articles:
        raise ValueError("조문 본문이 없는 응답")
    law_id = str(match["법령ID"])
    master = str(match["법령일련번호"])
    if not law_id.isdigit() or not master.isdigit():
        raise ValueError("법령 식별자 오류")
    return {
        "source": "국가법령정보센터", "api_target": "eflaw", "law_name": name,
        "law_id": law_id, "master_id": master,
        "effective_date": effective, "promulgation_date": clean_text(info.get("공포일자")),
        "promulgation_number": clean_text(info.get("공포번호")),
        "collected_at": collected_at,
        "source_url": f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={master}&efYd={effective}",
        "articles": articles,
        # 부칙·별표의 복잡한 구조와 첨부 링크는 응답 그대로 보존한다.
        "supplementary": redact_auth(body.get("부칙", {})),
        "annexes": redact_auth(body.get("별표", {})),
    }


class LawClient:
    def __init__(self, oc: str):
        if not oc:
            raise ValueError("LAW_OC_KEY 미설정")
        self.oc = oc
        self.session = requests.Session()

    def get(self, endpoint: str, **params) -> dict:
        try:
            response = self.session.get(f"{BASE}/{endpoint}", params={
                "OC": self.oc, "target": "eflaw", "type": "JSON", **params,
            }, timeout=(10, 40))
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("JSON 객체가 아닌 응답")
            return data
        except (requests.RequestException, ValueError) as exc:
            # requests 예외 문자열에는 OC를 포함한 URL이 들어갈 수 있다.
            raise RuntimeError(f"국가법령 API 요청 실패 ({type(exc).__name__}); 인증·접근 설정을 확인하세요") from None

    def fetch(self, name: str) -> tuple[dict, dict]:
        matches = []
        page = 1
        while True:
            payload = self.get("lawSearch.do", query=name, search=1, nw=3, display=100, page=page)
            listing = payload.get("LawSearch")
            if not isinstance(listing, dict) or "totalCnt" not in listing:
                raise ValueError("법령 목록 응답 형식 오류; 인증·접근 설정을 확인하세요")
            rows = as_list(listing.get("law"))
            matches.extend(row for row in rows if re.sub(r"\s", "", row.get("법령명한글", "")) == re.sub(r"\s", "", name))
            if page * 100 >= int(listing["totalCnt"]):
                break
            if not rows or page >= 100:
                raise ValueError("법령 목록 페이지 불완전")
            page += 1
            time.sleep(0.2)
        if len(matches) != 1:
            raise ValueError(f"현행 법령 정확 일치 결과 {len(matches)}건; 법령명 확인 필요")
        match = matches[0]
        body = self.get("lawService.do", MST=match["법령일련번호"], efYd=match["시행일자"])
        return match, body


def save_law(root: Path, payload: dict, match: dict, collected_at: str) -> dict:
    record = normalize_law(payload, match, collected_at)
    raw = json.dumps(redact_auth(payload), ensure_ascii=False, sort_keys=True, indent=2)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    # 같은 원문 재수집은 같은 경로를 사용하고 개정된 원문은 별도 스냅샷을 만든다.
    directory = root / f"{record['law_id']}_{record['master_id']}_{record['effective_date']}_{digest[:16]}"
    directory.mkdir(parents=True, exist_ok=True)
    record["raw_sha256"] = digest
    for filename, content in (("raw.json", raw), ("law.json", json.dumps(record, ensure_ascii=False, indent=2))):
        temp = directory / (filename + ".tmp")
        temp.write_text(content, encoding="utf-8")
        temp.replace(directory / filename)
    return {"law_name": record["law_name"], "status": "collected", "directory": directory.name,
            "articles": len(record["articles"]), "effective_date": record["effective_date"], "raw_sha256": digest}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="부동산 현행법령 원문 별도 수집 (기존 챗봇 DB 변경 없음)")
    parser.add_argument("--laws", help="쉼표로 구분한 법령명; 생략하면 기본 대상")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "law_corpus")
    parser.add_argument("--list", action="store_true", help="수집 대상만 확인")
    args = parser.parse_args(argv)
    names = list(dict.fromkeys(name.strip() for name in args.laws.split(",") if name.strip())) if args.laws else DEFAULT_LAWS
    if args.list:
        print("\n".join(names))
        return 0
    load_dotenv(ROOT / ".env")
    oc = os.getenv("LAW_OC_KEY") or os.getenv("LAW_API_KEY")
    if not oc:
        print("LAW_OC_KEY / LAW_API_KEY 미설정: .env에 국가법령정보 공동활용 API 인증값을 설정하세요.", file=sys.stderr)
        return 2
    client = LawClient(oc)
    collected_at = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    results = []
    args.output.mkdir(parents=True, exist_ok=True)
    for name in names:
        try:
            match, payload = client.fetch(name)
            result = save_law(args.output, payload, match, collected_at)
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
            result = {"law_name": name, "status": "failed", "error_type": type(exc).__name__}
        results.append(result)
        print(f"{name}: {result['status']}", flush=True)
        time.sleep(0.2)
    manifest = {"collected_at": collected_at, "results": results, "scope": "현행 법령 본문·부칙·별표 메타데이터; 첨부파일 다운로드 제외"}
    (args.output / ("manifest_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 1 if any(result["status"] == "failed" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
