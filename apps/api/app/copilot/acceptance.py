"""Server-owned completion rubric, frozen before generation; never authored by the verifier."""
from .v31_contracts import AcceptanceCriterion
import re
import hashlib
import json
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DocumentAcceptance:
    """One request-level rubric shared by every long-read stage and source span."""
    request: str
    mode: str
    required: tuple[str, ...]
    not_required: tuple[str, ...]
    version: str = 'document-acceptance-v1'

    def payload(self):
        value = asdict(self)
        value['acceptance_id'] = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return value


def freeze_document_acceptance(plan):
    # Narrow only an explicit qualification deliverable. Broader/compound goals
    # retain their original request; a procedure request must never be dropped.
    question = re.sub(r'\s+', '', plan.goal)
    qualification = bool(re.search(r'참가(?:자격|요건)|참여자격', question))
    procedures = any(word in question for word in ('절차', '제출방법', '작성방법', '입찰방법', '산출내역', '취소', '개찰', '예정가격',
                                                    '제출서류', '제출기한', '입찰보증', '청렴', '서약', '계약조건', '정산'))
    submission = any(word in question for word in ('입찰서작성', '입찰서제출', '작성·제출', '작성및제출', '제출방법'))
    qualification_excluded = bool(re.search(r'참가자격을[^.!?]{0,30}(?:아니|제외|빼)', question))
    broader = any(word in question for word in ('개찰', '낙찰', '예정가격', '계약체결', '정산'))
    if submission and not broader and (not qualification or qualification_excluded):
        return DocumentAcceptance(request=plan.goal, mode='SUBMISSION',
            required=('입찰서 작성방식·금액·산출내역서, 제출기간·방법, 수정·취소 제한을 설명한다.',
                      '제출 시 필요한 서류·보증확약·서약 동의 등 원문에 명시된 제출 의무와 그 주체·기한·예외를 보존한다.',
                      '모든 원문 부분의 관련 여부를 검토한다. 해당 부분에 없는 내용을 그 부분의 누락으로 요구하지 않는다.'),
            not_required=('개찰 일시·전산장애에 따른 개찰 지연, 예정가격 산정·낙찰자 선정·계약 이행은 작성·제출 요청의 완료 조건이 아니다.',
                          '참가자격 자체의 업종·소재지·현장방문 조건은 별도 요청하지 않은 한 완료 조건이 아니다. 단, 명시된 필수 제출서류는 포함한다.'))
    narrow = qualification and not procedures and not submission
    return DocumentAcceptance(request=plan.goal, mode='QUALIFICATIONS' if narrow else 'REQUEST_SCOPE',
        required=(('참가자의 자격·업종·등록·허가·소재지 및 참가 인정에 직접 결부된 현장 방문·확인서 조건을 설명한다.',
                   '위 조건에 붙은 의무 주체·등록기한·적용기간·수치·부정·대안·예외를 보존한다. 등록정보 일치 등 자격의 유효성 조건도 포함한다.') if narrow
                  else ('원래 request에서 요청한 모든 주제·조건·절차를 설명한다. 참가자격으로 범위를 축소하지 않는다.',))
                  + ('번호가 다른 업종군의 AND/OR가 원문에서 명확하지 않으면 관계를 단정하지 않고 검수 필요를 설명한다.',
                     '모든 원문 부분의 관련 여부를 검토한다. 부분에 없는 정보나 다른 부분의 내용을 그 부분의 누락으로 요구하지 않는다.'),
        not_required=(('전자입찰의 제출 방법, 총액·산출내역서 작성, 제출 취소·수정, 개찰·예정가격 산정 등 절차 자체는 이 참가자격 요청의 완료 조건이 아니다.',
                       '일반 청렴·안전 서약의 제재 상세, 계약 후 수행·정산, 빈 서식 항목의 열거는 이 참가자격 요청의 완료 조건이 아니다.') if narrow else ()))


def answerable_checks_request(question):
    """Only narrow an explicit request for additional answer/input questions."""
    compact = re.sub(r'\s+', '', question).rstrip('.!?。')
    return bool(re.fullmatch(
        r'(?:추가(?:로)?답변(?:이)?필요한|답변입력가능한|추가입력이필요한)'
        r'(?:확인)?질문(?:만|을|들을|목록을)?(?:알려줘|보여줘|정리해줘|알려주세요|보여주세요|정리해주세요)', compact))


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
