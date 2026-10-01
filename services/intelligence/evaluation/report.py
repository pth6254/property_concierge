"""평가 원문은 실행 폴더에만 저장하고 HTML에서는 반드시 이스케이프한다."""
from __future__ import annotations

from collections import Counter
import html
import json
from pathlib import Path
import statistics


def summarize(results: list[dict]) -> dict:
    counts = Counter(result["status"] for result in results)
    measured = [r["elapsed_seconds"] for r in results]
    suites = {}
    for suite in sorted({r["suite"] for r in results}):
        members = [r for r in results if r["suite"] == suite]
        statuses = Counter(r["status"] for r in members)
        metrics = {}
        for key in sorted({key for r in members for key in r.get("metrics", {})}):
            values = [r["metrics"][key] for r in members if isinstance(r.get("metrics", {}).get(key), (int, float))]
            metrics[key] = statistics.mean(values) if values else None
        suites[suite] = {"total": len(members), "passed": statuses["pass"], "failed": statuses["fail"],
                         "errors": statuses["error"], "mean_metrics": metrics}
    return {"total": len(results), "passed": counts["pass"], "failed": counts["fail"], "errors": counts["error"], "suites": suites,
            "pass_rate": counts["pass"] / len(results) if results else None,
            "median_seconds": statistics.median(measured) if measured else None,
            "review_required": sum(bool(r.get("review_required")) for r in results)}


def write_report(directory: Path, metadata: dict, results: list[dict]) -> dict:
    directory.mkdir(parents=True, exist_ok=False)
    summary = summarize(results)
    report = {"schema_version": 1, "metadata": metadata, "summary": summary, "results": results}
    (directory / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    reviews = [{"id": result["id"], "repeat": result["repeat"], "status": "pending",
                "scores": {"relevance": None, "groundedness": None, "context_retention": None, "clarity": None},
                "critical_error": None, "reviewer": "", "notes": ""}
               for result in results if result.get("review_required")]
    (directory / "human_review.json").write_text(json.dumps({"run_id": metadata["run_id"], "reviews": reviews}, ensure_ascii=False, indent=2), encoding="utf-8")
    esc = html.escape
    cards = []
    for result in results:
        checks = "".join(f"<li class={'pass' if c['passed'] else 'fail'}>{'통과' if c['passed'] else '실패'} · {esc(c['name'])} "
                         f"<small>기대 {esc(str(c.get('expected')))} / 실제 {esc(str(c.get('actual')))}</small></li>" for c in result.get("checks", []))
        turns = "".join(f"<div class=turn><b>사용자</b><p>{esc(t['question'])}</p><b>답변</b><p>{esc(t['answer'])}</p>"
                        f"<small>검토: {esc(t['review_focus'])}</small></div>" for t in result.get("details", {}).get("turns", []))
        steps = []
        for step in result.get("details", {}).get("steps", []):
            rows = []
            for row in step["comparison"]["rows"]:
                actions = step["next_actions"].get(str(row["property_id"]), [])
                price = "미입력" if row["asking_price"] is None else f"{row['asking_price']:,}원"
                rows.append(f"<tr><td>{esc(row['name'])}</td><td>{price}</td><td>{'등록 검토 완료' if row['decision_ready'] else '추가 확인 필요'}</td>"
                            f"<td>{esc(', '.join(a['title'] for a in actions) or '없음')}</td></tr>")
            summary_text = esc(json.dumps(step["execution"]["summary"], ensure_ascii=False))
            steps.append(f"<div class=turn><b>{esc(step['name'])}</b><p>기준 시각 {esc(step['as_of'])}</p><div class=table-wrap><table>"
                         "<thead><tr><th>후보</th><th>희망가</th><th>검토 상태</th><th>다음 행동</th></tr></thead><tbody>" + "".join(rows)
                         + f"</tbody></table></div><details><summary>실행 준비 상태</summary><p>{summary_text}</p></details></div>")
        scope = result.get("details", {}).get("scope") or result.get("details", {}).get("method") or ""
        details = esc(json.dumps(result.get("details", {}), ensure_ascii=False, indent=2))
        cards.append(f"<article data-status='{esc(result['status'])}'><h2>{esc(result['suite'])} / {esc(result['id'])} "
                     f"<span class='{esc(result['status'])}'>{esc(result['status'])}</span></h2>"
                     f"<p>반복 {result['repeat']} · {result['elapsed_seconds']:.2f}초"
                     f"{' · 사람 검토 필요' if result.get('review_required') else ''}</p><p>{esc(scope)}</p>{turns}{''.join(steps)}<ul>{checks}</ul>"
                     f"<details><summary>실행 근거와 추적 정보</summary><pre>{details}</pre></details></article>")
    document = """<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>부동산 컨시어지 평가 결과</title><style>
body{font:15px/1.65 system-ui,sans-serif;background:#f1f5f9;color:#172033;margin:0}main{max-width:1100px;margin:auto;padding:32px}
article,header{background:white;padding:24px;border:1px solid #dbe3ec;border-radius:12px;margin:18px 0}h1{margin:0}h2{font-size:18px}
.pass{color:#047857}.fail,.error{color:#b91c1c}small{color:#64748b}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f8fafc;padding:16px}
p{white-space:pre-wrap;overflow-wrap:anywhere}.turn{border-left:3px solid #94a3b8;padding:12px 18px;margin:16px 0}select{padding:8px}
.table-wrap{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:10px;text-align:left;border-bottom:1px solid #e2e8f0}td{min-width:100px}
</style><main><header><h1>부동산 컨시어지 평가 결과</h1>
<p>자동 검사는 대화 품질·현행 법령 적합성을 보증하지 않습니다. 계산 기대값의 출처와 기준일, 검색 방식, 사람 검토 항목을 확인하세요.</p>
""" + f"<p>실행 {esc(metadata['run_id'])} · 통과 {summary['passed']} / 실패 {summary['failed']} / 오류 {summary['errors']} · 사람 검토 {summary['review_required']}</p>" + f"<details><summary>실행 설정·영역별 지표</summary><pre>{esc(json.dumps({'metadata': metadata, 'suites': summary['suites']}, ensure_ascii=False, indent=2))}</pre></details>" + """
<label>결과 필터 <select id="filter"><option value="all">전체</option><option value="fail">실패</option><option value="error">오류</option><option value="pass">통과</option></select></label>
</header>""" + "".join(cards) + """</main><script>document.getElementById('filter').addEventListener('change',e=>document.querySelectorAll('article').forEach(a=>a.hidden=e.target.value!=='all'&&a.dataset.status!==e.target.value));</script></html>"""
    (directory / "report.html").write_text(document, encoding="utf-8")
    return report
