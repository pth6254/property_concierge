"""법령 검색 결과가 생성·출처·비동기 API까지 전달되는지 검증한다."""
import time
from types import SimpleNamespace
import pytest

from tests.test_market_explorer import client
from tests.test_law_vector_ingestion import isolated_law_tables


def test_official_context_and_sources(monkeypatch):
    from backend.services import chat_service, law_retrieval
    import model_factory
    contexts = []
    monkeypatch.setattr(law_retrieval, "search_laws", lambda *a, **k: [{
        "title": "주택임대차보호법 제3조의3", "source": "국가법령정보센터", "text": "임차권등기명령을 신청할 수 있다.",
        "url": "https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq=1", "effective_date": "20260101", "origin": "official_law"}])
    def invoke(messages):
        contexts.append(messages)
        return SimpleNamespace(content="임차권등기명령을 신청할 수 있습니다.")
    monkeypatch.setattr(model_factory, "get_llm_json", lambda: SimpleNamespace(invoke=lambda _: SimpleNamespace(content='{"tool":"none"}')))
    monkeypatch.setattr(model_factory, "get_llm", lambda: SimpleNamespace(invoke=invoke))
    result = chat_service.answer_question("보증금 미반환")
    assert result['sources'][0]['origin'] == 'official_law'
    assert result['sources'][0]['effective_date'] == '20260101'
    assert '시행일 20260101' in str(contexts)


def test_unavailable_official_store_does_not_invent_answer(monkeypatch):
    from backend.services import chat_service, law_retrieval
    import model_factory
    monkeypatch.setattr(law_retrieval, 'search_laws', lambda *a, **k: [])
    monkeypatch.setattr(model_factory, 'get_llm_json', lambda: SimpleNamespace(invoke=lambda _: SimpleNamespace(content='{"tool":"none"}')))
    monkeypatch.setattr(model_factory, 'get_llm', lambda: pytest.fail('근거 없는 생성'))
    result = chat_service.answer_question('관계없는 질문')
    assert not result['sources'] and '자료를 찾지 못했습니다' in result['answer']


def test_pgvector_reassembles_article_and_filters_supplements(isolated_law_tables, monkeypatch):
    from backend.tools.embed_property_laws import ingest_law, DIMENSIONS
    from backend.services import law_retrieval
    class Embedder:
        digest = 'fixture-law-chat'
        def __init__(self, *a): pass
        def embed(self, texts): return [[1.0] + [0.0] * (DIMENSIONS - 1) for _ in texts]
    monkeypatch.setenv('OLLAMA_HOST', 'http://unused.invalid')
    monkeypatch.setattr(law_retrieval, 'Embedder', Embedder)
    body = '법령 본문' * 500
    law = {'raw_sha256':'law-chat','law_id':'1','law_name':'가상 법령','source_url':'https://www.law.go.kr/',
        'effective_date':'20260101','collected_at':'2026-09-10', 'articles':[{
            'number':'1','branch_number':'','title':'목적','text':body,'is_article':'조문'}],
        'supplementary':{'부칙단위':{'부칙내용':'과거 부칙'}}}
    ingest_law(law, Embedder())
    chunks = law_retrieval.search_laws('질문')
    assert len(chunks) == 1 and chunks[0]['text'] == body


def test_chat_job_owner_and_result(client, monkeypatch):
    from backend.services import chat_service
    monkeypatch.setattr(chat_service, 'answer_question', lambda *a: {'answer':'법령 답변','sources':[], 'tool_used':None,'disclaimer':'안내','blocked':[]})
    created = client.post('/api/chat/jobs', json={'message':'질문'})
    assert created.status_code == 200
    url = '/api/chat/jobs/' + created.json()['job_id']
    for _ in range(100):
        body = client.get(url).json()
        if body['status'] in ('done','error'): break
        time.sleep(.01)
    assert body['status'] == 'done' and body['result']['answer'] == '법령 답변'
    client.cookies.clear()
    assert client.get(url).status_code == 404


def test_concierge_reuses_guarded_answer_without_regeneration(monkeypatch):
    from backend.services import chat_service
    from backend.graphs.concierge_graph import execute_node, explain_node
    from schemas.concierge import ConciergeDecision
    monkeypatch.setattr(chat_service, 'answer_question', lambda q, history=None: {'answer':q,'sources':[{'title':'공식 법령'}],'blocked':['위조 숫자']})
    state = execute_node({'decision':ConciergeDecision(intent='tax_legal'),'user_id':1,'message':'원문 질문'})
    output = explain_node(state)
    assert output['answer'] == '원문 질문' and output['blocked'] == ['위조 숫자']
    assert output['tool_result'].data['sources']
