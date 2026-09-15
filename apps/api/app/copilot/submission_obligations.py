"""Render every proposed obligation field before semantic verification.

Rows are model proposals, never authoritative extraction or persisted eligibility.
The same document at two stages remains two independently cited claims.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class SubmissionObligation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    document: str = Field(min_length=1, max_length=500)
    stage: str = Field(min_length=1, max_length=200)
    obligation: Literal['필수', '협조', '조건부', '확인 필요']
    deadline: str = Field(min_length=1, max_length=300)
    method: str = Field(min_length=1, max_length=300)
    timing: Literal['예정일 경과', '예정', '시점 미확정']
    conditions: str = Field(min_length=1, max_length=600)


def render_obligation(row: SubmissionObligation) -> str:
    # Nothing from a structured row bypasses the existing claim verifier.
    return (f'[{row.stage} · {row.obligation}] {row.document}\n'
            f'기한: {row.deadline} ({row.timing}) · 제출 방법: {row.method}\n'
            f'조건·확인할 일: {row.conditions}')


INSTRUCTIONS = '''
제출 서류·참석 준비물은 submission으로 구조화한다. 일반 설명은 submission=null이다.
서류(같은 단계·기한·방법·의무인 서류 묶음 가능), 제출 단계, 필수/협조/조건부/확인 필요,
기한, 방법, 예정일 상태, 예외·확인할 일을 각각 원문 근거로 작성한다.
같은 서류가 입찰과 계약에 모두 등장하면 각 단계별 별도 claim으로 남긴다.
한 단계의 기재가 다른 단계의 의무를 없애지 않는다. 실제 상충은 확인 필요로 표시한다.
날짜나 방법이 없으면 원문에 미기재라고 쓰고 추측하지 않는다.
예정일 경과는 행사 개최·참석·제출 완료를 뜻하지 않는다. 실제 이행은 확인할 일로 남긴다.
서버가 submission의 모든 필드를 표시 문장으로 변환해 검증하므로 text에 다른 사실을 추가하지 않는다.
필수와 협조는 별도 claim으로 나누고 단계 순서로 배치한다. 빈 서식과 작성 목차는 나열하지 않는다.
'''
