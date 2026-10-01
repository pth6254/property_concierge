"""연결 실패·결과 오염 때 Python 수식으로 대체하지 않는 계산 계약 검증."""
import pytest
import requests
from fastapi import HTTPException

from backend.services.core_calculations import calculate
from schemas.simulation import SimulationInput


def configure(monkeypatch):
    monkeypatch.setenv("CORE_STORAGE_URL", "http://core.test:8080")
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "test-internal-secret-" + "a" * 32)


def test_disconnected_calculator_never_falls_back(monkeypatch):
    configure(monkeypatch)
    def disconnected(*args, **kwargs):
        raise requests.ConnectionError("isolated")
    monkeypatch.setattr(requests, "post", disconnected)
    from backend.router import run_simulation
    with pytest.raises(HTTPException) as caught:
        run_simulation(SimulationInput(purchase_price=600_000_000))
    assert caught.value.status_code == 503
    import tax_rules
    with pytest.raises(HTTPException) as caught:
        tax_rules.calc_gift_tax(500_000_000)
    assert caught.value.status_code == 503


@pytest.mark.parametrize("status,expected", [(401, 503), (500, 503), (422, 422)])
def test_rejected_service_response_is_not_a_success(monkeypatch, status, expected):
    configure(monkeypatch)
    response = requests.Response(); response.status_code = status
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    with pytest.raises(HTTPException) as caught:
        calculate("simulation", {"purchase_price": 1})
    assert caught.value.status_code == expected


def test_result_from_different_inputs_is_rejected(monkeypatch):
    from backend.tools.simulation_tool import run_simulation
    original = run_simulation(SimulationInput(purchase_price=500_000_000)).model_dump(mode="json")
    original["calculator_engine"] = "kotlin-spring"
    configure(monkeypatch)
    response = requests.Response(); response.status_code = 200
    import json
    response._content = json.dumps(original).encode()
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)
    with pytest.raises(HTTPException) as caught:
        run_simulation(SimulationInput(purchase_price=600_000_000))
    assert caught.value.status_code == 503


def test_decimal_ratio_does_not_lose_a_won():
    from api.routes.simulation import SimulationRequest
    assert SimulationRequest(purchase_price=100, loan_ratio=0.58).to_simulation_input().loan_amount == 58
