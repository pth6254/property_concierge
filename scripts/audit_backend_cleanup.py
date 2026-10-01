"""대체된 Python 구현 제거와 실행 중 API·워커의 코드 일치를 확인한다."""
from __future__ import annotations

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()


import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

from audit_python_routes import ROOT, audit

MODULES = [
    'api/ai_context.py', 'api/main.py', 'api/data_routes.py', 'api/analysis_routes.py', 'api/history_db.py', 'api/activity_db.py', 'api/case_db.py',
    'api/case_execution_db.py', 'api/jobs.py', 'api/core_bridge.py',
    'backend/services/listing_store.py', 'backend/services/listing_observations.py',
    'backend/services/case_snapshot_presentation.py', 'backend/services/core_calculations.py',
    'backend/services/candidate_funding.py', 'backend/tools/simulation_tool.py', 'backend/tax_rules.py',
    'backend/services/funding_execution_client.py', 'backend/concierge/decision_tools.py',
    'backend/services/case_funding_scenarios.py', 'schemas/funding_request.py',
    'schemas/purchase_case.py', 'schemas/listing_import.py',
    *['api/routes/' + name + '.py' for name in ('chat', 'appraisal', 'concierge', 'rights', 'comparison', 'recommendation')],
]
MODULES = ["services/intelligence/" + name for name in MODULES]

# 호스트 3.12와 컨테이너 3.11의 AST 차이를 제거하되 실행 코드와 상수는 모두 비교한다.
FINGERPRINT_CODE = '''
import ast, hashlib, json, pathlib, sys
result = {}
for name in json.loads(sys.stdin.read()):
    tree = ast.parse(pathlib.Path(name).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if hasattr(node, "type_params"):
            delattr(node, "type_params")
    result[name] = hashlib.sha256(ast.dump(tree).encode()).hexdigest()
print(json.dumps(result))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--containers', nargs='*', default=[])
    parser.add_argument('--output', type=Path, default=ROOT / 'evaluation-results/cleanup-code-audit.json')
    args = parser.parse_args()
    report = {'status': 'passed', 'routes': audit(), 'contracts': {}, 'containers': {}}
    for decorator in ('core_store', 'core_calculation'):
        count = 0
        for name in MODULES:
            tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef):
                    continue
                if not any(isinstance(d, ast.Call) and isinstance(d.func, ast.Name) and d.func.id == decorator
                           for d in node.decorator_list):
                    continue
                count += 1
                body = node.body
                if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                    body = body[1:]
                if not (len(body) == 1 and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                        and body[0].value.value is Ellipsis):
                    raise RuntimeError(f'계약에 중복 실행 구현이 있습니다: {name}:{node.name}')
        report['contracts'][decorator] = count
    expected = {}
    for name in MODULES:
        tree = ast.parse((ROOT / name).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if hasattr(node, 'type_params'):
                delattr(node, 'type_params')
        expected[name] = hashlib.sha256(ast.dump(tree).encode()).hexdigest()
    for container in args.containers:
        response = subprocess.run(['docker', 'exec', '-i', container, 'python', '-c', FINGERPRINT_CODE],
            input=json.dumps(MODULES), text=True, capture_output=True, check=True)
        actual = json.loads(response.stdout)
        different = [name for name in MODULES if actual.get(name) != expected[name]]
        report['containers'][container] = {'status': 'failed' if different else 'passed',
            'matched_modules': len(MODULES) - len(different), 'different_modules': different}
        if different:
            report['status'] = 'failed'
    if report['routes']['status'] != 'passed':
        report['status'] = 'failed'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return int(report['status'] != 'passed')


if __name__ == '__main__':
    raise SystemExit(main())
