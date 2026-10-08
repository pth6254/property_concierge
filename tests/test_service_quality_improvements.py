"""실거래 비교·자금 추천·공식 검색·과거 AVM·사용자 의견의 의미 있는 경계를 검증한다."""
import pytest
from tests.test_market_explorer import client


def test_market_same_area_year_filters_do_not_cast_unknown_year(client):
    from db.base import session_scope
    from db.models import Transaction
    with session_scope() as session:
        session.add_all([Transaction(endpoint="RTMSDataSvcAptTrade",category="주거용",lawd_cd="11680",deal_ym="202608",
            price=price,area_sqm=area,per_sqm=price/area,apt_name=str(price),year_built=year,is_cancelled=False)
            for price,area,year in [(30000,40,"2020"),(70000,84,"2018"),(80000,84,"미상"),(200000,130,"2020")]])
    body=client.get("/api/market/regions/summary",params={"region_code":"1100000000","property_type":"apartment",
        "area_min_sqm":80,"area_max_sqm":90,"min_build_year":2015,"max_build_year":2020}).json()
    assert body["items"][0]["median_price"]==70000
    assert body["items"][0]["sample_size"]==1
    assert not body["items"][0]["comparison_eligible"]
    assert body["criteria"]["area_min_sqm"]==80
    assert client.get("/api/market/regions/summary",params={"region_code":"1100000000","area_min_sqm":90,"area_max_sqm":80}).status_code==422


def test_recommendations_use_actual_funding_and_keep_asking_price_unset(monkeypatch):
    from backend.services import complex_recommend_service as service
    rows=[{"apt_name":name,"dong":"반포동","price":price,"area_sqm":84,"per_sqm":price/84,
        "year_built":"2018","deal_year":2026,"deal_month":8} for name,price in [("낮은 부담",50000),("높은 부담",80000)] for _ in range(3)]
    monkeypatch.setattr(service,"get_lawd_code",lambda _:"11650")
    monkeypatch.setattr(service,"_load_samples",lambda *a:rows)
    monkeypatch.setattr(service,"_apply_time_adjustment",lambda rows,*a:(rows,0))
    monkeypatch.setattr(service,"enrich_complex_addresses",lambda *a:None)
    profile={"cash_available":350000000,"emergency_reserve":10000000,"monthly_payment_limit":2000000,
        "loan_ratio":.5,"annual_interest_rate":4,"loan_years":30,"owned_homes":1,"adjusted_area":False,"annual_income":80000000}
    result=service.recommend_complexes("서초구",priority="cash",buyer_profile=profile)
    assert result["results"][0]["complex_name"]=="낮은 부담"
    first,second=[row["funding_preview"]["summary"] for row in result["results"]]
    assert first["required_cash"]<second["required_cash"]
    assert first["cash_available"]==340000000
    assert all("asking_price" not in row for row in result["results"])


def test_saved_region_snapshot_keeps_case_comparison_conditions(client):
    from db.base import session_scope
    from db.models import Transaction
    with session_scope() as session:
        session.add_all([Transaction(endpoint="RTMSDataSvcAptTrade",category="주거용",lawd_cd="11680",deal_ym="202608",
            price=price,area_sqm=area,apt_name="검증단지",year_built="2018",is_cancelled=False)
            for price,area in [(70000,84),(200000,130)]])
    case=client.post("/api/cases",json={"title":"동일 조건 저장","buyer_profile":{"min_area_sqm":80,"max_area_sqm":90,"min_build_year":2015,"max_build_year":2020}}).json()
    saved=client.post(f"/api/cases/{case['id']}/regions",json={"region_code":"1168000000","property_type":"apartment","months":12})
    assert saved.status_code==201
    snapshot=saved.json()["stats_snapshot"]
    assert snapshot["sample_size"]==1 and snapshot["median_price"]==70000
    assert snapshot["comparison_criteria"]["area_max_sqm"]==90


def test_official_rag_does_not_pass_on_summary_fallback_or_wrong_law(monkeypatch):
    from backend.services import law_retrieval
    from evaluation.schema import RagCase
    from evaluation.suites import rag
    case=RagCase(id="official",question="질문",relevant_articles=[{"law_id":"001248","article":"제3조의3"}],require_official_law=True)
    def source(question,k,trace):
        trace.update(mode="keyword")
        return [{"law_id":"001248","article":"제3조의3","title":"임차권"}]
    monkeypatch.setattr(law_retrieval,"retrieve_chat_evidence",source)
    assert rag(case,live=True,k=4)["status"]=="fail"
    def wrong(question,k,trace):
        trace.update(mode="pgvector_law")
        return [{"law_id":"009276","article":"제3조의3","title":"다른 법"}]
    monkeypatch.setattr(law_retrieval,"retrieve_chat_evidence",wrong)
    assert rag(case,live=True,k=4)["status"]=="fail"
    with pytest.raises(ValueError,match="live"):
        rag(case,live=False,k=4)


def test_real_agent_replay_excludes_target_month_and_future(monkeypatch):
    from evaluation.production_avm import replay_one
    target={"deal_ym":"202608","apt_name":"검증단지","dong":"반포동","area_sqm":84,"price":50000,"floor":"10","year_built":"2010"}
    prior={**target,"price":49000,"per_sqm":49000/84,"deal_ym":"202607","deal_year":2026,"deal_month":7,"is_cancelled":False}
    leak={**prior,"price":99999999,"per_sqm":99999999/84}
    result=replay_one(target,{"202607":[prior]*3,"202608":[leak],"202609":[leak]},"11650","서초구")
    assert result["estimated"] and result["estimated_manwon"]<60000
    assert result["comparable_count"]==3
    assert all(month<"202608" for month in result["prior_months"])
    cancelled={**prior,"is_cancelled":True}
    absent=replay_one(target,{"202607":[cancelled]},"11650","서초구")
    assert not absent["estimated"] and absent["ape"] is None


def test_policy_replay_withholds_below_five_and_classifies_reason():
    from evaluation.production_avm import replay_one
    target={"deal_ym":"202608","apt_name":"검증단지","dong":"반포동","area_sqm":84,"price":50000,"floor":"10","year_built":"2010"}
    def trade(day):
        return {**target,"price":49000,"per_sqm":49000/84,"deal_ym":"202607","deal_year":2026,"deal_month":7,"deal_day":str(day),
                "floor":str(day),"is_cancelled":False}
    enough=replay_one(target,{"202607":[trade(day) for day in range(1,6)]},"11650","서초구",policy=True)
    assert enough["estimated"] and enough["result_kind"]=="market_reference" and enough["withheld_reason"]==""
    few=replay_one(target,{"202607":[trade(day) for day in range(1,4)]},"11650","서초구",policy=True)
    assert not few["estimated"] and few["ape"] is None and few["result_kind"]=="withheld"
    assert few["withheld_reason"]=="insufficient_samples"
    empty=replay_one(target,{},"11650","서초구",policy=True)
    assert not empty["estimated"] and empty["withheld_reason"] in {"complex_not_matched","no_recent_trades"}


def test_feedback_owner_operator_status_and_anonymous_boundaries(client,monkeypatch):
    own=client.get("/api/auth/me").json()["id"]
    result=client.post("/api/feedback",json={"feature":"explore","category":"confusing","message":"면적 조건 안내가 어려워요"})
    assert result.status_code==201
    feedback_id=result.json()["id"]
    assert client.get("/api/operations/feedback").status_code==403
    from tests.test_operations import operator
    operator(client,monkeypatch)
    assert client.get("/api/operations/feedback").json()["items"][0]["id"]==feedback_id
    assert client.patch(f"/api/operations/feedback/{feedback_id}",json={"status":"resolved"}).json()["status"]=="resolved"
    assert client.post("/api/feedback",json={"feature":"other","category":"error","message":"   "}).status_code==422
    client.cookies.clear()
    assert client.post("/api/feedback",json={"feature":"chat","category":"error","message":"답변 오류"}).status_code==401
    client.post("/api/auth/register",json={"email":"feedback-other@example.com","password":"test-password-1234","name":"other"})
    assert client.get("/api/feedback").json()["items"]==[]
    assert client.get("/api/operations/feedback").status_code==403


def test_metrics_deduplicate_jobs_and_users_without_storing_raw_url(client,monkeypatch):
    from api.service_metrics import record_duration
    from db.redis_client import get_redis
    redis=get_redis()
    for key in redis.scan_iter("metrics:*"):redis.delete(key)
    record_duration("job:test",.2,False,job_id="unique")
    record_duration("job:test",10,True,job_id="unique")
    record_duration("job:test",3,True,job_id="different")
    own=client.get('/api/auth/me').json()['id']
    for _ in range(2):
        assert client.post('/api/cases',json={'title':'고유 사용자 집계 검증'}).status_code==201
    from tests.test_operations import operator
    operator(client,monkeypatch)
    result=client.get('/api/operations/metrics?days=1').json()
    row=next(row for row in result['features'] if row['feature']=='job:test')
    assert row["requests"]==2 and row["failures"]==1 and row["p95_upper_seconds"]==3
    assert result["steps"]["case_created"]==1
    members=[member for key in redis.scan_iter("metrics:step:*") for member in redis.smembers(key)]
    assert str(own) not in members
