"""Python 프로세스(API·작업 실행기)의 Sentry 초기화. SENTRY_DSN 미설정 시 완전히 비활성.

DSN이 없으면 sentry_sdk.init을 아예 호출하지 않으므로 로컬 개발·CI에는 영향이 없다.
send_default_pii=False로 고정한다: 이 서비스는 주소 마스킹·질문 축약 저장 등 개인정보 최소화 원칙을
지키고 있는데, Sentry가 기본값으로 요청 IP·쿠키까지 전송하게 두면 그 원칙이 오류 보고 경로에서만 깨진다.

작업 실행기는 API와 다른 프로세스라 API의 초기화가 적용되지 않는다. 실행기의 실패는 대부분
`logger.exception`으로 처리되므로 기본 로깅 통합(ERROR 이상을 이벤트로 전송)으로 보고된다.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_error_tracking(service: str) -> bool:
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    import sentry_sdk

    environment = os.getenv("APP_ENV", "development")
    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=os.getenv("SENTRY_RELEASE", "").strip() or None,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
    )
    sentry_sdk.set_tag("service", service)
    logger.info("Sentry 오류 추적 활성화 (service=%s, environment=%s)", service, environment)
    return True
