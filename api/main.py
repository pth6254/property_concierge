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

from api.routes import appraisal, chat, comparison, concierge, recommendation, rights
from api import data_routes, analysis_routes
from backend.cache_db import init_cache_db as _init_cache
from db.base import init_db

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
    from api.core_bridge import require_core_configuration
    require_core_configuration()
    init_db()
    _init_cache()
    logger.info("AI 서비스 시작 — 분석 스키마·캐시 초기화 완료")
    yield
    logger.info("FastAPI 종료")


app = FastAPI(
    title="Property Concierge 내부 AI·데이터 서비스",
    description="Spring이 인증한 입력의 모델 추정·RAG·랭킹·데이터 분석",
    version="1.0.0",
    lifespan=lifespan,
)


from api.internal_contracts import router as internal_router
app.include_router(internal_router)


@app.middleware("http")
async def internal_service_boundary(request, call_next):
    if request.url.path not in ("/health", "/ready"):
        import hmac
        from fastapi.responses import JSONResponse
        expected = os.getenv("INTERNAL_SERVICE_SECRET", "")
        provided = request.headers.get("X-Internal-Service-Key", "")
        if len(expected) < 32 or not provided or not hmac.compare_digest(expected, provided):
            return JSONResponse({"detail": "내부 서비스 인증이 필요합니다"}, status_code=401)
    return await call_next(request)


@app.middleware("http")
async def measure_request(request, call_next):
    import asyncio
    from time import perf_counter
    from api.service_metrics import record_duration
    started, status_code = perf_counter(), 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        # 매물 ID·쿼리·주소가 포함된 실제 URL은 집계 키로 사용하지 않는다.
        template = getattr(route, "path", None)
        if template and template.startswith("/internal/v1/"):
            await asyncio.to_thread(record_duration, f"http:{request.method}:{template}", perf_counter()-started, status_code >= 500)

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

for _router in (appraisal.router, recommendation.router, comparison.router,
                concierge.router, rights.router, chat.router, data_routes.router, analysis_routes.router):
    app.include_router(_router)


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["system"])
def readiness():
    from fastapi.responses import JSONResponse
    from api.operational_health import snapshot
    state = snapshot()
    # 공개 경로에는 내부 큐·인프라 정보를 노출하지 않는다.
    return JSONResponse({"status": state["status"]}, status_code=200 if state["status"] == "ready" else 503)
