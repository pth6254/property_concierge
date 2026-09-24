"""법률 도구가 사용자별 서버 대화를 이어받고 새 대화에서는 비워지는지 검증한다."""
from tests.test_market_explorer import client
from tests.test_concierge_validation import route


def test_legal_tool_receives_previous_turns_from_server(client, monkeypatch):
    from backend.services import chat_service
    calls = []
    def answer(question, history=None):
        calls.append((question, list(history or [])))
        return {'answer': '검증용 답변', 'sources': [], 'disclaimer': '참고 정보'}
    monkeypatch.setattr(chat_service, 'answer_question', answer)
    route(monkeypatch, {'intent': 'tax_legal', 'criteria': {}})
    first = client.post('/api/concierge/messages', json={'message':'성인 자녀에게 5억 증여하면?'}).json()
    assert first['status'] == 'completed'
    assert calls[0][1] == []
    second = client.post('/api/concierge/messages', json={'message':'그럼 배우자는?', 'conversation_id':first['conversation_id']}).json()
    assert second['status'] == 'completed'
    assert calls[-1][1][0] == {'role':'user', 'content':'성인 자녀에게 5억 증여하면?'}
    assert calls[-1][0] == '그럼 배우자는?'
    client.post('/api/concierge/messages', json={'message':'새로운 법률 질문'})
    assert calls[-1][1] == []

    client.cookies.clear()
    assert client.post('/api/auth/register',json={'email':'legal-other@example.com','password':'legal-other-12345','name':'다른 사용자'}).status_code == 201
    client.post('/api/concierge/messages',json={'message':'그럼 배우자는?', 'conversation_id':first['conversation_id']})
    assert calls[-1][1] == []
