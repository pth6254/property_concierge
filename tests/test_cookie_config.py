"""Spring의 실제 쿠키 헤더 회귀 검증. 환경 조합은 Kotlin CookieContractTest에서 검증한다."""
from tests.test_market_explorer import client

def test_issued_cookie_matches_development_configuration(client):
    response=client.post('/api/auth/register',json={'email':'cookie-header@example.com','password':'cookie-password-1234','name':'쿠키'})
    assert response.status_code==201,response.text
    header=response.headers['set-cookie'].lower()
    assert 'samesite=lax' in header and 'httponly' in header and 'path=/' in header
    assert 'secure' not in header

def test_logout_clears_same_cookie_attributes(client):
    response=client.post('/api/auth/logout')
    header=response.headers['set-cookie'].lower()
    assert 'samesite=lax' in header and 'httponly' in header and 'path=/' in header and 'max-age=0' in header
    assert client.get('/api/auth/me').status_code==401
