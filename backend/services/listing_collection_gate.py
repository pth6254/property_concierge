"""계정·실행기·평가기 전체가 같은 외부 수집 대기 시간을 공유한다."""
from db.redis_client import get_redis

KEY = "listing-collection:naver:next-request"
INTERVAL_SECONDS = 60
BLOCK_SECONDS = 900


def remaining() -> int:
    return max(0, get_redis().ttl(KEY))


def reserve() -> int:
    # 확인과 예약을 원자적으로 수행해 여러 실행기가 동시에 브라우저를 열지 못하게 한다.
    return int(get_redis().eval("""
        if redis.call('SET', KEYS[1], 'interval', 'NX', 'EX', ARGV[1]) then
            return 0
        end
        return math.max(1, redis.call('TTL', KEYS[1]))
    """, 1, KEY, INTERVAL_SECONDS))


def postpone(seconds: int) -> int:
    # 뒤늦은 짧은 제한 응답이 기존의 긴 대기 시간을 줄이지 않도록 한다.
    return int(get_redis().eval("""
        local wait = math.max(tonumber(ARGV[1]), redis.call('TTL', KEYS[1]))
        redis.call('SET', KEYS[1], 'blocked', 'EX', wait)
        return wait
    """, 1, KEY, max(BLOCK_SECONDS, seconds)))


def wait_message(seconds: int) -> str:
    return (f"네이버 원문 수집을 잠시 쉬고 있습니다. 약 {seconds}초 후 직접 다시 시도해주세요. "
            "자동 재시도하지 않습니다. 원문을 확인할 수 있다면 링크로 수동 등록할 수 있습니다.")
