"""서비스 호스트 밖에서 실행하는 준비 상태 감시. 알림 URL을 지정해야 외부 알림을 전송한다."""
import argparse
import json
import os
import time
from urllib.request import Request,urlopen
from urllib.parse import urlsplit


def probe(url):
    try:
        with urlopen(url,timeout=10) as response:
            return response.status==200 and json.load(response).get("status")=="ready"
    except Exception:
        return False


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default=os.getenv("EXTERNAL_READINESS_URL",""))
    parser.add_argument("--once",action="store_true")
    args=parser.parse_args()
    if urlsplit(args.url).scheme not in {"http","https"} or urlsplit(args.url).username:
        parser.error("인증정보가 없는 HTTP(S) 준비 상태 URL을 지정하세요")
    previous=None
    while True:
        ready=probe(args.url)
        print("ready" if ready else "unavailable",flush=True)
        webhook=os.getenv("OPS_ALERT_WEBHOOK_URL","")
        if ready!=previous and webhook:
            if urlsplit(webhook).scheme!="https":
                raise ValueError("알림 웹훅은 HTTPS 주소여야 합니다")
            try:
                body=json.dumps({"text":"부동산 컨시어지 서비스 복구" if ready else "부동산 컨시어지 준비 상태 점검 실패"}).encode()
                with urlopen(Request(webhook,data=body,headers={"Content-Type":"application/json"}),timeout=10):
                    pass
            except Exception:
                print("외부 알림 전달 실패",flush=True)
        previous=ready
        if args.once:return 0 if ready else 1
        time.sleep(60)


if __name__=="__main__":
    raise SystemExit(main())
