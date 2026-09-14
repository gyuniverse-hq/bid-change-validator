"""Server-owned completion rubric, frozen before generation; never authored by the verifier."""
from .v31_contracts import AcceptanceCriterion
import re


def profile_only_request(question):
    compact = re.sub(r'\s+', '', question)
    # A narrow, explicit read scope is authoritative. Compound requests still
    # reach the planner and cannot be collapsed into a single profile read.
    return bool(re.fullmatch(
        r'(?:현재|저장된|판정에사용한|판정에사용된|판정당시의?|우리회사의?)*'
        r'(?:회사정보|프로필)만'
        r'(?:(?:간단히|간단하게|짧게|항목별로)?(?:요약|정리|보여|알려|조회)(?:해줘요?|해주세요|줘|주세요|해)?)?'
        r'[.!?。]*', compact))


PROFILE_TOPICS = (
    ('identity', ('소재', '지역', '규모'), '저장된 회사 소재지와 규모를 요약한다.'),
    ('staff', ('인력', '직원', '경력'), '저장된 전체 인원과 주요 직무별 인원을 요약한다. 요청하지 않은 null 경력 연수 열거는 불필요하다.'),
    ('performance', ('실적',), '저장된 실적의 주요 내용과 금액을 요약한다. 없으면 저장된 실적이 없음을 설명한다.'),
    ('registration', ('업종', '등록', '면허', '인증'), '저장된 industries(업종)와 certifications(인증) 목록만 요약한다. 빈 목록은 정보 미등록이며 실제 미보유가 아니다. 별도 면허/등록 필드의 존재 확인을 요구하지 않는다.'),
)


def freeze_acceptance(plan, bundle):
    """Topic policies concern the deliverable, not newly judging the company.

    Every selected read remains represented. Unavailable reads get an empty-basis
    criterion and cannot be upgraded by an apology or a fabricated citation.
    """
    criteria = []
    kinds = ['READ_PROFILE'] if profile_only_request(plan.goal) else list(dict.fromkeys(t.kind for t in plan.tasks))
    for kind in kinds:
        tasks = [t for t in plan.tasks if t.kind == kind]
        facts = [f for f in bundle.facts if f.origin_tool == kind]
        # Unversioned synthetic/older adapters still get a request-scoped criterion.
        if not facts:
            expected = {'READ_PROFILE': {'PROFILE_FACT'}, 'READ_DOCUMENT': {'NOTICE_FACT'},
                        'READ_JUDGMENT': {'SERVER_RESULT'}, 'READ_CHECKS': {'SERVER_RESULT', 'NOTICE_FACT'},
                        'READ_CHANGES': {'SERVER_RESULT'}, 'REVIEW_ASSUMPTION': {'ASSUMPTION'}}.get(kind, set())
            facts = [f for f in bundle.facts if f.origin_tool is None and f.kind in expected]
        ids = tuple(f.fact_id for f in facts)
        def add(suffix, mode, requirement, basis=ids):
            criteria.append(AcceptanceCriterion(criterion_id=kind + ':' + suffix, task_kind=kind,
                mode=mode, requirement=requirement, fact_ids=basis))
        if kind == 'READ_CHECKS' and facts:
            for index, fact in enumerate(facts):
                add(str(index), 'CHECKLIST',
                    '이 항목에서 사용자가 확인/답변해야 하는 질문 또는 확인할 일을 조건·수치·예외와 함께 제시한다. '
                    '회사가 이미 충족한다는 결론이나 증빙 확보는 완료 요건이 아니다.', (fact.fact_id,))
        elif kind == 'READ_PROFILE' and len(kinds) == 1:
            broad = any(word in plan.goal.replace(' ', '') for word in ('회사정보', '프로필', '전체'))
            specific = [topic for topic in PROFILE_TOPICS if any(word in plan.goal for word in topic[1])]
            if broad and not any(word + '만' in plan.goal.replace(' ', '') for _, words, _ in PROFILE_TOPICS for word in words):
                specific = []
            for name, _, requirement in specific or PROFILE_TOPICS:
                add(name, 'PROFILE_SUMMARY', requirement)
        elif kind == 'PROPOSE_ACTION':
            add('request', 'EXPLANATION',
                '서버가 생성한 제안의 대상·입력 내용과 명시 확인 전 저장되지 않는다는 점을 설명한다. '
                '사용자 입력은 제안 값이며 증명된 회사 사실이 아니다. 실행·저장 완료를 요구하지 않는다.')
        elif kind == 'REVIEW_ASSUMPTION':
            add('request', 'EXPLANATION',
                '사용자 가정과 조회된 해당 요건을 비교해 가정하에서의 조건부 결론을 설명한다. '
                '검토 가정을 반복하는 것만으로 완료되지 않는다. 실제 보유·저장 판정 변경·전체 참가 가능으로 단정하지 않는다. '
                '복합 조건이나 필요한 근거가 부족하면 조건부 결론의 한계를 설명한다.')
        else:
            add('request', 'EXPLANATION', ' / '.join(t.question for t in tasks))
    return tuple(criteria)


def assess_acceptance(criteria, result, claims):
    """Model explains coverage; code owns the allowed criterion set and computes completeness."""
    rows = result.criteria
    expected = {c.criterion_id: c for c in criteria}
    if len(rows) != len(expected) or {r.criterion_id for r in rows} != set(expected):
        return {'task_coverage': 'PARTIAL', 'reason': 'CRITERION_SET_MISMATCH', 'criteria': [r.model_dump() for r in rows]}
    supported = {c.claim_id: c for c in claims if c.validation == 'SUPPORTED'}
    missing = []
    for row in rows:
        criterion = expected[row.criterion_id]
        valid = row.status == 'MET' and bool(row.claim_ids) and bool(criterion.fact_ids)
        cited_facts = set()
        for cid in row.claim_ids:
            claim = supported.get(cid)
            valid = valid and claim is not None
            if claim is not None:
                cited_facts.update(claim.fact_ids)
        # A criterion can be explained by several supported sentences: premise,
        # condition and limitation need not each cite the same premise fact.
        # Every sentence must be supported and their combined proof must still
        # contain the criterion's actual evidence.
        valid = valid and bool(cited_facts & set(criterion.fact_ids))
        if not valid:
            missing.append(row.criterion_id)
    return {'task_coverage': 'PARTIAL' if missing else 'COMPLETE', 'missing_criterion_ids': missing,
            'criteria': [r.model_dump() for r in rows]}
