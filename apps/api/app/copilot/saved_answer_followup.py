"""Scope saved-answer follow-ups to persisted receipts, never notice changes."""
import json
import re
from sqlalchemy import select
from ..ask_back_models import QualificationAnswer
from ..judgment_models import QualificationJudgmentRun
from ..qualification.rules.source_contracts import valid_contract, validate_confirmation_input
from . import product_tools


def followup_kind(message):
    text = re.sub(r'[\s.!?。？]', '', message)
    if re.fullmatch(r'(?:방금|최근)(?:반영|저장)한(?:내용|답변)(?:과현재판정)?(?:을)?(?:설명해줘|알려줘|요약해줘)', text):
        return 'receipt'
    if re.fullmatch(r'(?:현장방문)?확인(?:서|증)(?:를|을)?제출했다고가정하면(?:어떻게돼|어떻게되나요)', text):
        return 'assumption'
    if re.fullmatch(r'(?:아까|방금)(?:내가)?답변을잘못했어(?:수정|정정)하려면어떻게해야해', text):
        return 'correction'
    return None


def receipt_text(kind, summary, answer, source_run, requirement):
    """Only assert input meaning after the stored contract basis is validated."""
    current = {j.requirement_key:j for j in summary.judgments}
    if answer is None:
        return '현재 판정에 연결된 저장 답변을 찾지 못했습니다. 어느 요건의 답변인지 확인해 주세요. 공고 변경이나 입찰서 수정으로 해석하지 않았으며, 저장한 내용도 없습니다.'
    item = current.get(answer.requirement_key)
    if item is None:
        raise ValueError('ANSWER_REQUIREMENT_MISMATCH')
    contract = valid_contract(requirement)
    if not contract or contract['kind'] != 'SITE_VISIT':
        return '최근 저장 답변의 현장 방문 조건을 확인하지 못했습니다. 대상 요건을 지정해 주세요. 답변을 수정하거나 재판정하지 않았습니다.'
    validate_confirmation_input(contract, answer.normalized_value, answer.answer_json['satisfies_requirement'])
    values = json.loads(answer.normalized_value)['answers']
    counts = summary.judgment_counts
    status = {'eligible':'참가 가능', 'ineligible':'참가 불가', 'insufficient_data':'확인 필요'}[summary.overall_status]
    current_text = f"현재 저장 판정은 {status}이며, 충족 {counts.get('SATISFIED',0)}건·확인 필요 {counts.get('UNKNOWN',0)}건·미달 {counts.get('UNSATISFIED',0)}건입니다."
    if kind == 'correction':
        return ('앱에 저장한 현장 방문 답변의 수정 방법을 묻는 것으로 이해했습니다. 현재는 이미 판정된 답변을 직접 수정하는 기능이 없습니다. '
                '답변 입력은 확인 필요 상태의 요건만 허용됩니다. 기존 답변을 삭제하거나 다시 검토하도록 자동 실행하지 않았습니다. '
                '어떤 값을 잘못 입력했는지 알려주면 저장하지 않고 변경 영향을 설명할 수 있습니다. 입찰서 수정 금지 조항과는 다른 문제입니다.')
    others = [j.raw for j in summary.judgments if j.requirement_key != answer.requirement_key and j.status == 'UNSATISFIED']
    if kind == 'assumption':
        assumption = ('저장된 방문 완료 답변이 맞고 공고의 현장 방문 조건을 충족했다는 전제에서, 확인서도 제출했다고 가정하면 이 현장 방문 요건은 충족될 수 있습니다.'
                      if values['site_visited'] else '저장된 답변은 현장 방문 미완료입니다. 확인서 제출만 가정해서는 방문 완료 조건까지 충족했다고 볼 수 없습니다.')
        return (assumption + (' 다른 미달 요건은 그대로 남습니다: ' + ' / '.join(others) + ' 따라서 이 가정만으로 전체 참가 가능이라고 할 수 없습니다.' if others else ' 다른 요건과 분석 보류 범위도 확인해야 하므로 전체 참가 가능으로 확정하지 않습니다.')
                + ' 가정 설명일 뿐 답변 저장이나 재판정은 하지 않았습니다. ' + current_text)
    prior = next((j.status for j in source_run.judgments if j.requirement_key == answer.requirement_key), None)
    labels = {'UNKNOWN':'확인 필요','SATISFIED':'충족','UNSATISFIED':'미달'}
    return ('저장한 답변은 현장 방문 ' + ('완료' if values['site_visited'] else '미완료')
            + ', 확인서 ' + ('제출' if values['visit_certificate'] else '미제출') + '입니다. 사용자 답변이며 실제 증빙 확인을 뜻하지 않습니다. '
            + (f"해당 요건은 {labels[prior]}에서 {labels[item.status]}로 바뀌었습니다. " if prior in labels else '')
            + current_text + (' 다른 미달 요건: ' + ' / '.join(others) if others else '')
            + ' 이는 사용자 답변 반영 내역이며 공고 v1→v2 변경 설명이 아닙니다.')


def read_followup(kind, tools):
    summary = tools._summary()
    p = summary.provenance
    with tools.db.no_autoflush:
        answer = tools.db.scalar(select(QualificationAnswer).where(
            QualificationAnswer.preflight_case_id == tools.case.id,
            QualificationAnswer.result_judgment_run_id == p.judgment_run_id,
        ).order_by(QualificationAnswer.created_at.desc(), QualificationAnswer.id.desc()).limit(1))
        if answer is None:
            return receipt_text(kind, summary, None, None, None), '현재 판정에 연결된 저장 답변 없음'
        source = tools.db.get(QualificationJudgmentRun, answer.source_judgment_run_id)
        if source is None or (source.preflight_case_id, source.company_id, source.notice_version_id, source.analysis_run_id) != (p.case_id,p.company_id,p.notice_version_id,p.analysis_run_id):
            raise ValueError('ANSWER_SOURCE_SCOPE_MISMATCH')
        details = product_tools.get_explanation_evidence(tools.db, tools.case.id, [answer.requirement_key])
        if len(details) != 1 or details[0].provenance != p:
            raise ValueError('ANSWER_EVIDENCE_SCOPE_MISMATCH')
        text = receipt_text(kind, summary, answer, source, details[0].requirement)
        labels = {'SATISFIED': '충족', 'UNSATISFIED': '미달', 'UNKNOWN': '확인 필요'}
        values = json.loads(answer.normalized_value).get('answers', {}) if answer.normalized_value else {}
        inputs = ' / '.join(label + ': ' + ('예' if values[key] else '아니요')
                            for key, label in [('site_visited', '현장 방문 완료'),
                                               ('visit_certificate', '확인서 제출')]
                            if isinstance(values.get(key), bool))
        proof = ('저장된 사용자 답변: ' + (inputs or '입력 내용의 별도 확인 필요')
                 + '\n사용자 입력이며 실제 증빙 검증을 뜻하지 않습니다.'
                 + '\n현재 판정에 연결된 요건별 결과:\n'
                 + '\n'.join(labels.get(j.status, j.status) + ' — ' + j.raw for j in summary.judgments))
        return text, proof
