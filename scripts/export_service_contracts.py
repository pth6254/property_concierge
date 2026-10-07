"""현재 코드에서 내부 API 계약을 생성하고 명세 누락을 확인한다."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
AI = ROOT / 'services/intelligence'
sys.path.insert(0, str(AI))
from concierge_workspace import ensure_import_paths

ensure_import_paths()

def documents() -> dict[str, dict]:
    # 명세 추출에는 연결·LLM 호출·실제 자격증명이 필요하지 않다.
    os.environ.setdefault('DATABASE_URL', 'postgresql://contract:contract@localhost/real_estate_test')
    os.environ.setdefault('REDIS_URL', 'redis://localhost:6379/15')
    from api.main import app
    specification = app.openapi()
    specification['paths'] = {path: value for path, value in specification['paths'].items()
                              if path.startswith('/internal/v1/')}
    specification['components'].setdefault('securitySchemes', {})['InternalServiceKey'] = {
        'type': 'apiKey', 'in': 'header', 'name': 'X-Internal-Service-Key'}
    specification['security'] = [{'InternalServiceKey': []}]
    operations = []
    for path in sorted(AI.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in tree.body:
            if not isinstance(node, ast.FunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Name):
                    continue
                if decorator.func.id == 'core_store':
                    domain = ast.literal_eval(decorator.args[0])
                    route = f'/internal/v1/store/{domain}/{node.name}'
                elif decorator.func.id == 'core_calculation':
                    route = f'/internal/v1/calculations/{node.name}'
                else:
                    continue
                operations.append({'method': 'POST', 'path': route,
                    'signature': ast.unparse(node.args),
                    'return_annotation': ast.unparse(node.returns) if node.returns else None,
                    'source': path.relative_to(ROOT).as_posix()})
    # 데이터 객체를 통째로 전달하는 계약은 데코레이터 기반 스칼라 계약과 함께 명시한다.
    from schemas.income_valuation import IncomeValuationInput
    from schemas.valuation import ValuationAssessment
    operations.extend([
        {'method': 'POST', 'path': '/internal/v1/calculations/income_valuation',
         'source': 'services/intelligence/backend/services/valuation_support.py',
         'input_schema': IncomeValuationInput.model_json_schema(),
         'result_kinds': ['conditional_scenario', 'withheld'],
         'version': 'income-scenario-1.0'},
        {'method': 'POST', 'path': '/internal/v1/land/lookup',
         'source': 'services/intelligence/backend/services/valuation_support.py',
         'input_schema': {'type': 'object', 'required': ['address'], 'properties': {
             'address': {'type': 'string'}, 'as_of_date': {'type': 'string', 'default': ''}}},
         'result_kinds': ['public_reference'], 'version': 'land-information-1.0'},
    ])
    manifest = {'version': 1, 'authentication_header': 'X-Internal-Service-Key',
        'valuation_assessment_schema': ValuationAssessment.model_json_schema(),
        'units': {'money': 'KRW', 'area': 'm2'},
        'operations': sorted(operations, key=lambda item: item['path'])}
    return {'intelligence.openapi.json': specification, 'platform-client-contracts.json': manifest}

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    destination = ROOT / 'contracts/v1'
    destination.mkdir(parents=True, exist_ok=True)
    for name, document in documents().items():
        target = destination / name
        content = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        if args.check:
            if not target.exists() or target.read_text(encoding='utf-8') != content:
                raise SystemExit(f'계약 명세를 재생성하세요: {target.relative_to(ROOT)}')
        else:
            target.write_text(content, encoding='utf-8', newline='\n')
        print(f'{"확인" if args.check else "생성"}: contracts/v1/{name}')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
