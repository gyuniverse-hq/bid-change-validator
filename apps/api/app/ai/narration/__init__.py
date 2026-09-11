"""산문을 쓰는 경로. 판정은 하지 않는다.

이 패키지 안의 모듈은 **이미 확정된 결과를 말로 옮기기만** 한다. 적격·부적격을
새로 정하거나 숫자를 고르지 않는다. 판정은 `app.ai.qualification` 과
`app.ai.clause_review` 가 코드로 끝낸 뒤 이쪽으로 넘어온다.

`Narrator` 가 여기 있는 이유
---------------------------
산문 생성기는 (시스템 프롬프트, 본문) -> 텍스트 인 함수다. 그 이상을 요구하면
호출부가 특정 공급자에 묶인다. 실제 구현은 `app.ai.providers.openai` 에 있고,
테스트는 람다 하나로 대신한다.

타입 별칭을 패키지 최상단에 두는 것은 이 패키지의 모듈들이 서로를 import 하지
않고도 같은 이름을 쓰게 하기 위해서다. 요약·브리핑처럼 뒤에 붙는 모듈도
여기서 가져다 쓰면 된다 — 각자 다시 선언하면 같은 뜻의 타입이 둘이 된다.
"""

from __future__ import annotations

from collections.abc import Callable


Narrator = Callable[[str, str], str]

__all__ = ["Narrator"]
