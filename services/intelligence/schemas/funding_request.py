"""화면과 대화의 자금 입력을 공유하는 계약."""
from decimal import Decimal
from typing import Literal, Optional
from pydantic import BaseModel, Field


class SimulationRequest(BaseModel):
    case_id: int | None = None
    candidate_id: int | None = None
    purchase_price: int = Field(..., gt=0)
    cash_available: int | None = Field(None, ge=0)
    monthly_payment_limit: int | None = Field(None, ge=0)
    loan_ratio: float = Field(0.5, ge=0.0, le=0.9)
    annual_interest_rate: float = Field(4.0, ge=0.0, le=30.0)
    loan_years: int = Field(30, ge=1, le=50)
    repayment_type: Literal["equal_payment", "equal_principal", "interest_only"] = "equal_payment"
    holding_years: int = Field(3, ge=1, le=50)
    expected_annual_growth_rate: float = Field(0.0, ge=-20.0, le=50.0)
    rent_deposit: Optional[int] = None
    assumed_deposit: Optional[int] = Field(None, ge=0, description="승계할 기존 임차 보증금. 잔금에서 차감하며 반환 의무를 넘겨받음")
    rent_fee: Optional[int] = None
    monthly_management_fee: Optional[int] = None
    property_type: str = "아파트"
    owned_homes: int = Field(1, ge=1, le=100, description="취득 후 주택 수. 첫 주택 취득은 1")
    # 세금·규제 (선택)
    official_price: Optional[int] = None            # 공시가격 (원)
    residence_years: Optional[int] = None           # 거주 연수
    vacancy_rate: float = Field(5.0, ge=0.0, le=50.0)
    adjusted_area: bool = False                     # 조정대상지역
    annual_income: Optional[int] = None             # 연소득 (원, DSR)
    existing_loan_annual_payment: int = Field(0, ge=0)

    def to_simulation_input(self):
        from schemas.simulation import SimulationInput

        # 화면·대화·시나리오에서 필드를 따로 복사하면 같은 조건도 서로 다른 계산이 된다.
        values = self.model_dump(exclude={"case_id", "candidate_id", "loan_ratio", "monthly_payment_limit"})
        return SimulationInput(**values, loan_amount=int(Decimal(self.purchase_price) * Decimal(str(self.loan_ratio))))
