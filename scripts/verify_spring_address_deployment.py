"""실행 중인 Spring 주소 공급자 연결을 확인하고 검사 계정은 바로 제거한다."""
from __future__ import annotations

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()

import json
import secrets
import uuid
from pathlib import Path
import requests

def main():
    root='http://127.0.0.1:3002'
    session=requests.Session()
    registered=False
    report={'status':'running','checks':[], 'boundaries':['실제 Spring·카카오 주소 조회 연결','개별 호·매물 존재·호가 정확도는 검증하지 않음']}
    try:
        response=session.post(root+'/api/auth/register',json={'email':f'address-deployment-{uuid.uuid4().hex}@example.com',
            'password':secrets.token_urlsafe(24),'name':'주소 연결 검사'},timeout=10)
        assert response.status_code==201, f'가입 응답: {response.status_code}'
        registered=True
        response=session.get(root+'/api/listings/address/search',params={'query':'서울특별시 서초구 반포대로 275'},timeout=40)
        assert response.status_code==200, f'주소 조회 응답: {response.status_code}'
        items=response.json()['items']
        assert items and any(item['jibun_address'] and item['road_address'] for item in items),'지번·도로명 연결 결과 없음'
        assert all(len(item['legal_region_code'])==10 and item['token'] and item['checked_at'] for item in items)
        report['checks'].append('Caddy→Spring→실제 주소 공급자→도로명·지번·법정동·확인 시각·주소 증명 반환')
        report['status']='passed'
    except Exception as error:
        report.update(status='failed',error=str(error))
        raise
    finally:
        if registered:
            assert session.delete(root+'/api/auth/me',timeout=10).status_code==200,'검사 계정 제거 실패'
        output=Path(__file__).resolve().parents[1]/'evaluation-results/spring-address-deployment-result.json'
        output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__': main()
