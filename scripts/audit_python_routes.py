"""Kotlin으로 이전한 HTTP 경로가 Python에 다시 구현되는 것을 막는다."""
from __future__ import annotations

from pathlib import Path as _WorkspacePath
import sys as _workspace_sys
_workspace_sys.path.insert(0, str(_WorkspacePath(__file__).resolve().parents[1] / "services/intelligence"))
from concierge_workspace import ensure_import_paths as _ensure_import_paths
_ensure_import_paths()


import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalized(path: str) -> str:
    return re.sub(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", "{}", path)


def native_routes() -> list[dict]:
    routes = []
    for file in (ROOT / "services/platform/src/main/kotlin").rglob("*Controller.kt"):
        source = file.read_text(encoding="utf-8")
        prefix = re.search(r'@RequestMapping\("([^\"]+)"\)', source)
        prefix = prefix[1] if prefix else ""
        for annotation in re.finditer(r"@(Get|Post|Put|Patch|Delete)Mapping(?:\(([^\n]*?)\))?", source):
            paths = re.findall(r'"(/[^\"]*)"', annotation[2] or "") or [""]
            for path in paths:
                full = prefix + path
                if full.startswith("/api/") or full == "/api":
                    routes.append({"method": annotation[1].upper(), "path": full,
                        "normalized": normalized(full), "file": str(file.relative_to(ROOT))})
        if file.name == 'AiGatewayController.kt':
            mapping = re.search(r'@RequestMapping\((.*?)\)\s*fun', source, re.S)
            for path in re.findall(r'"(/api/[^\"]*)"', mapping[1] if mapping else ''):
                routes.append({'method':'GET' if '/conversations/' in path else 'POST', 'path':path,
                    'normalized':normalized(path),'file':str(file.relative_to(ROOT))})
    return routes


def python_routes() -> list[dict]:
    routes = []
    files = list((ROOT / "services/intelligence/api/routes").glob("*.py")) + list((ROOT / "services/intelligence/api").glob("*.py"))
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        prefix = ""
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                for keyword in node.value.keywords:
                    if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                        prefix = keyword.value.value
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name) and decorator.func.value.id == "router"
                        and decorator.func.attr in {"get", "post", "put", "patch", "delete"}):
                    path = prefix + ast.literal_eval(decorator.args[0]) if prefix.startswith('/internal/') else "/api" + prefix + ast.literal_eval(decorator.args[0])
                    routes.append({"method": decorator.func.attr.upper(), "path": path,
                        "normalized": normalized(path), "file": str(file.relative_to(ROOT)), "handler": node.name})
    return routes


def audit() -> dict:
    native = native_routes()
    keys = {(route["method"], route["normalized"]) for route in native}
    duplicates = [route for route in python_routes() if (route["method"], route["normalized"]) in keys]
    public = [route for route in python_routes() if route['path'].startswith('/api/')]
    forbidden = ['api/auth_db.py', 'api/auth_utils.py', 'api/deps.py', 'api/email_service.py', 'api/rate_limit.py',
        'backend/services/listing_address_service.py',
        *['api/routes/'+name+'.py' for name in ('auth','address','history','activity','feedback','listings','cases','operations','simulation','market')]]
    remaining = [path for path in forbidden if (ROOT / "services/intelligence" / path).exists() or (ROOT / path).exists()]
    return {"status": "failed" if duplicates or public or remaining else "passed", "native_count": len(native),
            "duplicates": duplicates, "python_public_routes":public, "replaced_files_remaining":remaining}


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(result['status'] != 'passed')
