"""
main.py — FastAPI 진입점

실행: uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 프로젝트 루트 및 backend/ 를 sys.path 선두에 삽입
_API_DIR      = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_API_DIR)
_BACKEND_DIR  = os.path.join(_PROJECT_ROOT, "backend")
for _p in [_PROJECT_ROOT, _BACKEND_DIR, _API_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.routes import activity, appraisal, address, auth, cases, chat, comparison, concierge, history, listings, market, recommendation, rights, simulation
from api import auth_db as _adb
from api import history_db as _hdb
from api import activity_db as _actdb
from api.rate_limit import limiter
from backend.cache_db import init_cache_db as _init_cache

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────
#  에러 추적 (Sentry) — SENTRY_DSN 미설정 시 완전히 비활성.
#
# 지금까지는 실사용자가 겪은 에러를 재현할 방법이 로그(stdout)뿐이었다.
# DSN이 없으면 sentry_sdk.init을 아예 호출하지 않으므로 로컬 개발·CI에는
# 영향이 없다 — 운영에서 발급받은 DSN을 .env에 넣는 순간에만 켜진다.
# send_default_pii=False로 고정한다: 이 서비스는 주소 마스킹·질문 축약
# 저장 등 개인정보 최소화 원칙을 이미 지키고 있는데, Sentry가 기본값으로
# 요청 IP·쿠키까지 전송하게 두면 그 원칙이 에러 리포팅 경로에서만 깨진다.
# ─────────────────────────────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        environment=os.getenv("APP_ENV", "development"),
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
    logger.info("Sentry 에러 추적 활성화 (environment=%s)", os.getenv("APP_ENV", "development"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _hdb.init()
    _adb.init()
    _actdb.init()
    _init_cache()
    logger.info("FastAPI 시작 — history DB, auth DB, activity DB, cache DB 초기화 완료")
    yield
    logger.info("FastAPI 종료")


app = FastAPI(
    title="부동산 감정평가 AI API",
    description="LangGraph 기반 부동산 가치 분석·추천·시뮬레이션 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 허용 오리진 — 배포 도메인은 CORS_ORIGINS 환경변수(콤마 구분)로 지정한다.
# 자격증명(쿠키)을 주고받으므로 와일드카드는 사용할 수 없다.
_DEFAULT_ORIGINS = "http://localhost:3000,http://frontend:3000"
CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", _DEFAULT_ORIGINS).split(",") if o.strip()
]
logger.info("CORS 허용 오리진: %s", CORS_ORIGINS)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for _router in [
    auth.router,
    appraisal.router,
    recommendation.router,
    simulation.router,
    comparison.router,
    cases.router,
    market.router,
    listings.router,
    concierge.router,
    history.router,
    activity.router,
    address.router,
    rights.router,
    chat.router,
]:
    app.include_router(_router, prefix="/api")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}
