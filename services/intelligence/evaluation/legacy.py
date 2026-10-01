"""기존 RAG 평가 질문을 정적 데이터로 옮긴다. Python 파일을 실행하지 않는다."""
from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

from evaluation.schema import Dataset


def import_rag(source: Path, *, question_key: str, titles_key: str, variable: str | None = None) -> Dataset:
    text = source.read_text(encoding="utf-8-sig")
    if source.suffix.lower() == ".py":
        if not variable:
            raise ValueError("Python 원본은 --variable로 정적 목록 이름을 지정하세요")
        values = []
        for node in ast.parse(text).body:
            if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == variable for target in node.targets):
                values.append(ast.literal_eval(node.value))
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == variable:
                values.append(ast.literal_eval(node.value))
        if len(values) != 1:
            raise ValueError("평가 목록을 단일 정적 리터럴로 지정하세요")
        data = values[0]
    elif source.suffix.lower() == ".jsonl":
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif source.suffix.lower() == ".csv":
        data = list(csv.DictReader(text.splitlines()))
    elif source.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("cases")
    else:
        raise ValueError("JSON·JSONL·CSV·Python 정적 목록만 지원합니다")
    if not isinstance(data, list) or not data:
        raise ValueError("원본 평가 사례 목록이 없습니다")
    cases = []
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict) or question_key not in item or titles_key not in item:
            raise ValueError("질문·정답 문서 필드 매핑을 확인하세요")
        titles = item[titles_key]
        if isinstance(titles, str):
            titles = json.loads(titles) if titles.lstrip().startswith("[") else [titles]
        cases.append({"id": str(item.get("id", f"legacy-{index:03}")), "question": item[question_key],
                      "relevant_titles": titles, "expect_no_results": item.get("expect_no_results", False)})
    result = Dataset(version="legacy-import-1", suite="rag", cases=cases)
    result.validated_cases()
    return result
