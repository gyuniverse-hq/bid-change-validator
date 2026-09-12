"""사업계획서 초안이 확정된 판정 결과에 충실한지 재는 장치.

무엇을 재고 무엇을 안 재나
--------------------------
글이 잘 쓰였는지는 재지 않는다. **확정된 사실을 그대로 옮겼는가**만 잰다.
골든셋 40케이스에 `eligible`(참가 가능)이 한 건도 없어서, 이 기능이 실제로 놓이는
상황은 언제나 "참가가 어렵거나 확인이 필요한데 초안을 요청받았다" 이다. 그때 가장
나쁜 실패는 문장이 어색한 것이 아니라 **못 한다는 사실을 숨기는 것**이다.

    골든셋 판정 JSON ─[코드 조판]→ 프롬프트 ─[모델]→ 초안 ─[코드 검사]→ 위반 수

모델은 가운데 한 번만 끼어든다. 앞뒤가 결정적이라 반복 실행에서 나오는 차이는
전부 모델 몫으로 돌릴 수 있다. 여기에 모델을 한 번 더 끼우면(예: 판정 결과를
모델에게 요약시키면) 요건이 빠졌을 때 범인이 둘이 되어 고칠 데를 못 찾는다.

모델이 쓴 글을 모델로 채점하지 않는 이유도 같다. 채점 모델의 실패와 생성 모델의
실패가 섞이면 어느 쪽 숫자인지 알 수 없다. 문자열 대조로 충분한 것만 잰다.

구성
----
`briefing_format`  판정 JSON -> 프롬프트 문자열. 초안 생성기가 되읽는 형식이라
                   계약이다. `verify_round_trip()` 이 모든 행이 되읽히는지 본다.
`conformance`      초안 검사. 누락·상태오기·모순이 안전 지표이고 0 이어야 한다.
`inputs`           담당자 입력 3종. 골든셋에 없는 부분이라 여기서 고정한다.

실행기는 `scripts/run_business_plan_eval.py` 에 있다. 골든셋 자체는 이 저장소에
없고(팀 공용 자료) 경로를 인자로 받는다.
"""

from .briefing_format import parse_qualification_items
from .briefing_format import render_briefing
from .briefing_format import verify_round_trip
from .conformance import DraftReport
from .conformance import Violation
from .conformance import check_draft
from .conformance import derive_content_hints
from .conformance import derive_user_claims
from .conformance import unattributed_claims
from .inputs import INPUT_SETS

__all__ = [
    "render_briefing",
    "parse_qualification_items",
    "verify_round_trip",
    "check_draft",
    "derive_content_hints",
    "derive_user_claims",
    "unattributed_claims",
    "DraftReport",
    "Violation",
    "INPUT_SETS",
]
