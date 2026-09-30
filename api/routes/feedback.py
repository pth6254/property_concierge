"""로그인 사용자의 문제 신고와 운영자의 처리 상태 관리."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from api.deps import get_current_user, require_operator
from api.rate_limit import limiter
from db.base import session_scope
from db.models import ServiceFeedback

router = APIRouter(tags=["feedback"])


class FeedbackInput(BaseModel):
    feature: Literal["explore","recommendation","cases","appraisal","simulation","rights","chat","listings","other"]
    category: Literal["error","confusing","incorrect","suggestion"]
    message: str = Field(min_length=3,max_length=2000)

    @field_validator("message")
    @classmethod
    def meaningful(cls, value):
        if len(value.strip()) < 3:
            raise ValueError("내용을 3자 이상 입력해주세요")
        return value.strip()


def view(item):
    return {"id":item.id,"feature":item.feature,"category":item.category,"message":item.message,"status":item.status,"created":item.created}


@router.post("/feedback",status_code=201)
@limiter.limit("10/hour")
def create(request:Request,body:FeedbackInput,user:dict=Depends(get_current_user)):
    with session_scope() as session:
        item = ServiceFeedback(user_id=user["id"],**body.model_dump())
        session.add(item)
        session.flush()
        return view(item)


@router.get("/feedback")
def mine(user:dict=Depends(get_current_user)):
    with session_scope() as session:
        return {"items":[view(item) for item in session.scalars(select(ServiceFeedback).where(ServiceFeedback.user_id==user["id"]).order_by(ServiceFeedback.id.desc()).limit(30))]}


@router.get("/operations/feedback")
def inbox(user:dict=Depends(require_operator)):
    with session_scope() as session:
        return {"items":[view(item) for item in session.scalars(select(ServiceFeedback).order_by(ServiceFeedback.id.desc()).limit(100))]}


class FeedbackUpdate(BaseModel):
    status: Literal["open","reviewing","resolved"]


@router.patch("/operations/feedback/{feedback_id}")
def update(feedback_id:int,body:FeedbackUpdate,user:dict=Depends(require_operator)):
    with session_scope() as session:
        item=session.get(ServiceFeedback,feedback_id)
        if not item:
            raise HTTPException(404,"문제 신고가 없습니다")
        item.status=body.status
        return view(item)
