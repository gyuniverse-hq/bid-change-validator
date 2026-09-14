"""Closed, source-bound contracts; unknown variants retain the composite guard."""
import hashlib
import re

VERSION = 'source-conditions-v1'


def compact(text):
    return re.sub(r'[\s·ㆍ․]', '', text)


def industry_identity(value, raw):
    text = str(value or '').strip()
    match = re.fullmatch(r'(?:(?P<name>[^()0-9]+)\s*\(\s*(?:업종코드\s*[:：]?\s*)?)?(?P<code>[0-9]{4})\s*\)?', text)
    if not match:
        return None
    codes = set(re.findall(r'(?<!\d)(\d{4})(?!\d)', raw))
    # Only code expressions, never dates/statute numbers, can establish identity.
    source_codes = set(re.findall(r'(?:업종\s*코드\s*[:：]?\s*|업\s*\(\s*)(\d{4})(?!\d)', raw))
    code = match['code']
    if source_codes and source_codes != {code}:
        return ('', '')
    if match['name'] and code not in codes:
        return ('', '')
    return code, (match['name'] or '').strip()


def transport_contract(raw):
    normalized = compact(raw)
    grammar = (r'(?:\d+\))?(?:「폐기물관리법」제\d+조에따른)?폐기물수집운반업\(\d{4}\)등록업체\.?'
               r'[○※]?단,처분또는재활용업허가(?:를받은)?업체가관계법령상해당폐기물을직접수집운반할수있는'
               r'장비허가조건을갖춘경우(?:에는)?수집운반업등록을별도로요구하지않을수있다\.')
    if not re.fullmatch(grammar, normalized):
        return None
    codes = set(re.findall(r'폐기물수집운반업\((\d{4})\)', normalized))
    required = ('관계법령상해당폐기물을직접수집운반할수있는', '장비허가조건을갖춘경우',
                '수집운반업등록을별도로요구하지않을수있다')
    if len(codes) != 1 or not all(t in normalized for t in required):
        return None
    # The positive conditional is deliberately narrow; negated/changed wording
    # and other composite arrangements cannot opt into this contract.
    if any(t in normalized for t in ('공동수급', '미보유', '아니', '갖추지', '제외한다')):
        return None
    return {'version': VERSION, 'kind': 'WASTE_TRANSPORT', 'code': next(iter(codes)),
            'raw_sha256': hashlib.sha256(raw.encode()).hexdigest()}


def valid_contract(requirement):
    stored = requirement.scope.get('source_contract')
    if not isinstance(stored, dict) or stored.get('version') != VERSION or not requirement.evidence_keys:
        return None
    if stored.get('raw_sha256') != hashlib.sha256(requirement.raw.encode()).hexdigest():
        return None
    if requirement.operator != 'MATCH' or requirement.condition_complexity != 'composite':
        return None
    if requirement.type != ('REGISTRATION_CERTIFICATION' if stored.get('kind') == 'SITE_VISIT' else 'INDUSTRY'):
        return None
    if stored.get('kind') == 'WASTE_TRANSPORT':
        return stored if stored == transport_contract(requirement.raw) and str(requirement.value) == stored['code'] else None
    if stored.get('kind') == 'INDUSTRY_ANY':
        codes = re.findall(r'폐기물(?:중간처분|중간재활용|종합재활용)업\s*\((\d{4})\)', requirement.raw)
        grammar = r'폐기물중간처분업\(\d{4}\)또는폐기물중간재활용업\(\d{4}\)또는폐기물종합재활용업\(\d{4}\)등록업체'
        if (sorted(set(codes)) == stored.get('codes') and len(codes) >= 2
                and re.fullmatch(grammar, compact(requirement.raw)) and requirement.value == ' / '.join(stored['codes'])):
            return stored
    if stored.get('kind') == 'SITE_VISIT':
        raw = compact(requirement.raw)
        if re.fullmatch(r'현장방문확인서제출업체에한하여입찰참가를(?:허용|인정)한다\.', raw):
            return stored
    return None


def confirmation_fields(contract):
    if contract['kind'] == 'WASTE_TRANSPORT':
        return [('disposal_permit', '해당 폐기물의 처분 또는 재활용업 허가를 보유함'),
                ('legal_transport_permission', '해당 폐기물을 직접 운반할 법적 허가 조건을 확인함'),
                ('required_equipment', '그 허가에 필요한 운반 장비 조건을 충족함')]
    if contract['kind'] == 'SITE_VISIT':
        return [('site_visited', '공고가 정한 현장 방문을 완료함'), ('visit_certificate', '현장 방문 확인서를 제출함')]
    return []


def validate_confirmation_input(contract, normalized_value, satisfies_requirement):
    import json
    try:
        answer = json.loads(normalized_value or '')
        fields = {key for key, _ in confirmation_fields(contract)}
        values = answer['answers']
        if (set(answer) != {'basis', 'answers'} or answer['basis'] != contract['raw_sha256']
                or set(values) != fields or any(type(v) is not bool for v in values.values())
                or satisfies_requirement != all(values.values())):
            raise ValueError('Incomplete or mismatched confirmation')
        return all(values.values())
    except (ValueError, KeyError, TypeError):
        from ..judgment import QualificationJudgmentError
        raise QualificationJudgmentError('STRUCTURED_CONFIRMATION_REQUIRED',
            '해당 원문의 허가·장비 또는 현장 확인 조건을 각각 답변해야 합니다. 단순 예/아니요로 적용할 수 없습니다.', status_code=422)
