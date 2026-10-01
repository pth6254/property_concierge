import os
import urllib.parse
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(BASE_DIR, ".env"))

key = os.getenv("MOLIT_API_KEY", "")
encoded_key = urllib.parse.quote(key, safe='')

BASE = "http://apis.data.go.kr/1613000"
LAWD = "11440"   # 마포구
YMD  = "202501"

endpoints = {
    "아파트 매매":    "/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "연립다세대 매매": "/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
    "단독다가구 매매": "/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
    "오피스텔 매매":  "/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
    "상업업무용 매매": "/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
    "공장창고 매매":  "/RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
    "토지 매매":     "/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
}

import requests
print("=" * 50)
for name, endpoint in endpoints.items():
    url = f"{BASE}{endpoint}?serviceKey={encoded_key}&LAWD_CD={LAWD}&DEAL_YMD={YMD}&numOfRows=1&pageNo=1"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200 and "<item>" in res.text:
            print(f"✅ {name}: 정상 ({res.text.count('<item>')}건)")
        elif res.status_code == 200:
            print(f"⚠️  {name}: 200이지만 데이터 없음")
        else:
            print(f"❌ {name}: {res.status_code}")
    except Exception as e:
        print(f"❌ {name}: {e}")
print("=" * 50)