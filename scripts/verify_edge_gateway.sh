#!/bin/sh
# Vercel 배포용 API 게이트웨이(infrastructure/proxy/Caddyfile.api) 검증.
# 격리 네트워크에 받은 헤더를 돌려주는 가짜 core를 두고 다음을 확인한다:
#   비밀 없는 /api 거부(403), 비밀이 맞으면 X-Client-IP → X-Forwarded-For 전달·비밀 헤더 제거,
#   클라이언트가 위조한 X-Forwarded-For는 무시, /ready는 비밀 없이 통과.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
net="pc-edge-test-$$"
secret="edge-test-secret-$$"
cleanup() { docker rm -f "$net-core" "$net-gw" >/dev/null 2>&1 || true; docker network rm "$net" >/dev/null 2>&1 || true; }
trap cleanup EXIT
docker network create "$net" >/dev/null
docker run -d --name "$net-core" --network "$net" --network-alias core caddy:2-alpine \
  caddy respond --listen :8080 --body 'xff={http.request.header.X-Forwarded-For};secret={http.request.header.X-Edge-Proxy-Secret};client={http.request.header.X-Client-IP}' >/dev/null
docker run -d --name "$net-gw" --network "$net" -e API_DOMAIN=":80" -e EDGE_PROXY_SECRET="$secret" \
  -v "$root/infrastructure/proxy/Caddyfile.api:/etc/caddy/Caddyfile:ro" caddy:2-alpine >/dev/null
sleep 2
probe() { docker run --rm --network "$net" curlimages/curl:8.10.1 -s -o - -w ' [%{http_code}]' "$@"; }
fail=0
check() { name=$1; expected=$2; actual=$3; case "$actual" in *"$expected"*) echo "PASS $name";; *) echo "FAIL $name: $actual"; fail=1;; esac; }
check "비밀 없는 /api 거부" "[403]" "$(probe http://$net-gw/api/auth/me)"
check "틀린 비밀 거부" "[403]" "$(probe -H 'X-Edge-Proxy-Secret: wrong' http://$net-gw/api/auth/me)"
check "비밀이 맞으면 접속 IP 전달·비밀 제거" "xff=203.0.113.7;secret=;client= [200]" \
  "$(probe -H "X-Edge-Proxy-Secret: $secret" -H 'X-Client-IP: 203.0.113.7' http://$net-gw/api/auth/me)"
check "위조한 X-Forwarded-For 무시" "xff=203.0.113.7;" \
  "$(probe -H "X-Edge-Proxy-Secret: $secret" -H 'X-Client-IP: 203.0.113.7' -H 'X-Forwarded-For: 1.2.3.4' http://$net-gw/api/cases)"
check "/ready는 비밀 없이 통과" "[200]" "$(probe http://$net-gw/ready)"
check "웹 경로는 거부" "[403]" "$(probe http://$net-gw/)"
exit "$fail"
