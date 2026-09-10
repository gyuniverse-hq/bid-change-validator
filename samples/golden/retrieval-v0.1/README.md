# 참가자격 검색 골든셋 v0.1

청크 ID 대신 원문 문자열 스팬을 라벨로 사용합니다. 청킹 방식이 바뀌어도 공백을 제거한
문자열이 청크 안에 남아 있으면 같은 라벨로 측정됩니다.

- `POSITIVE`: 실제 참가자격 요건
- `TRAP`: 참가자격 어휘를 포함하지만 요건이 아닌 목차·벌칙·평가 문언
- `document_id`: 동일 문언이 중복 문서에 있을 때 라벨의 출처를 고정
- `role`: `NOTICE`, `RFP`, `FORM`, `DUPLICATE`

현재는 하네스 기준선을 검증하기 위한 공고 1건, POSITIVE 4개, TRAP 2개가 들어 있습니다.
품질 비교를 주장하기 전 목표는 공고 8~10건, POSITIVE 60~90개, TRAP 40개입니다.

```bash
python -m apps.api.app.scripts.retrieval_report \
  --goldenset samples/golden/retrieval-v0.1 --retriever default --json
```
