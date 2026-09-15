"""슬롯 금액 전용 정규화. 기간/식수 결과를 금액으로 쓰지 않고 최소 금액을 가정하지 않는다."""
from __future__ import annotations
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
import math
import re
import unicodedata

MONEY_VERSION = 'qualification-slot-money-v1'
_DIGIT = r'(?:[1-9][0-9]{0,2}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?'
_PART = rf'(?:{_DIGIT}\s*(?:천만|백만|십만|조|억|만|천|백|십)?|[영공일이삼사오육륙칠팔구십백천만억조]+)'
_EXPR = re.compile(rf'(?:금\s*)?(?P<number>{_PART}(?:\s+{_PART})*)\s*원(?:정)?\s*(?P<op>이상|초과|이하|미만|이내)?')
_TAX = re.compile(r'\(\s*(?:부가세|부가가치세)\s*(?:포함|별도|제외)\s*\)')
_TOKEN = re.compile(rf'{_DIGIT}|[영공일이삼사오육륙칠팔구십백천만억조]')
_OPS = {'이상': '>=', '초과': '>', '이하': '<=', '미만': '<', '이내': '<='}
_HANGUL = dict(zip('영공일이삼사오육륙칠팔구', (0,0,1,2,3,4,5,6,6,7,8,9)))
_SMALL = {'십':10, '백':100, '천':1000}
_GROUP = {'만':10**4, '억':10**8, '조':10**12}


def failed_money(raw, code):
    return {'raw': raw, 'value': None, 'unit': 'KRW', 'op': None,
            'parse_status': 'failed', 'parse_notes': code}


def _number(text: str) -> int | float:
    tokens = _TOKEN.findall(text)
    if re.sub(r'\s+', '', ''.join(tokens)) != re.sub(r'\s+', '', text):
        raise ValueError('INVALID_MONEY_NUMBER')
    total = section = Decimal(0)
    number = None
    section_started = False
    last_small, last_group = 10000, 10**16
    with localcontext() as context:
        context.prec = max(50, len(text) * 2)
        for token in tokens:
            if token[0].isdigit() or token in _HANGUL:
                if number is not None:
                    raise ValueError('AMBIGUOUS_MONEY_NUMBER')
                number = Decimal(token.replace(',', '')) if token[0].isdigit() else Decimal(_HANGUL[token])
            elif token in _SMALL:
                if _SMALL[token] >= last_small:
                    raise ValueError('INVALID_MONEY_UNIT_ORDER')
                last_small = _SMALL[token]
                section_started = True
                section += (number if number is not None else Decimal(1)) * _SMALL[token]
                number = None
            else:
                if _GROUP[token] >= last_group:
                    raise ValueError('INVALID_MONEY_UNIT_ORDER')
                last_group, last_small = _GROUP[token], 10000
                explicit_value = section_started or number is not None
                section += number if number is not None else Decimal(0)
                total += (section if explicit_value else Decimal(1)) * _GROUP[token]
                section, number, section_started = Decimal(0), None, False
        value = total + section + (number or Decimal(0))
    if not value.is_finite() or value < 0:
        raise ValueError('INVALID_MONEY_NUMBER')
    if value == value.to_integral_value():
        return int(value)
    converted = float(value)
    if not math.isfinite(converted) or Decimal(str(converted)) != value:
        raise ValueError('MONEY_PRECISION_LOSS')
    return converted


def normalize_slot_money(raw: str) -> dict:
    if not isinstance(raw, str) or not raw.strip() or len(raw) > 1000:
        return failed_money(raw, 'INVALID_MONEY_EXPRESSION')
    text = unicodedata.normalize('NFKC', raw).strip()
    if len(_TAX.findall(text)) > 1:
        return failed_money(raw, 'MULTIPLE_MONEY_TAX_BASES')
    text = _TAX.sub(' ', text).strip()
    try:
        found = list(_EXPR.finditer(text))
        residue = _EXPR.sub('', text)
        if not found or len(found) > 2 or residue.strip(' \t\r\n,~～∼'):
            return failed_money(raw, 'MONEY_ROLE_OR_UNIT_MISMATCH')
        if text[:found[0].start()].strip():
            return failed_money(raw, 'INVALID_MONEY_EXPRESSION')
        values = [(_number(m['number']), _OPS.get(m['op'])) for m in found]
        if len(values) == 1:
            value, op = values[0]
            return {'raw': raw, 'value': value, 'unit': 'KRW', 'op': op,
                    'parse_status': 'success', 'parse_notes': ''}
        lows = [(n, op) for n, op in values if op in ('>=', '>')]
        highs = [(n, op) for n, op in values if op in ('<=', '<')]
        if len(lows) != 1 or len(highs) != 1 or lows[0][0] > highs[0][0] or (
            lows[0][0] == highs[0][0] and (lows[0][1] == '>' or highs[0][1] == '<')):
            return failed_money(raw, 'UNRESOLVED_MONEY_RANGE')
        return {'raw': raw, 'value': None, 'unit': 'KRW', 'op': None,
                'range': {'min': lows[0][0], 'min_op': lows[0][1],
                          'max': highs[0][0], 'max_op': highs[0][1]},
                'parse_status': 'success', 'parse_notes': ''}
    except (ValueError, InvalidOperation, OverflowError):
        return failed_money(raw, 'INVALID_MONEY_NUMBER')


def money_normalization_error(amount: object, raw: str | None = None) -> str | None:
    if not isinstance(amount, Mapping) or amount.get('parse_status') != 'success':
        return 'MONEY_PARSE_FAILED'
    if amount.get('unit') != 'KRW':
        return 'MONEY_UNIT_MISMATCH'
    def numeric(value):
        return (not isinstance(value, bool) and isinstance(value, (int, float))
                and (not isinstance(value, float) or math.isfinite(value)) and value >= 0)
    if amount.get('value') is not None:
        if (not numeric(amount['value']) or amount.get('range')
                or amount.get('op') not in (None, '=', '>=', '>', '<=', '<')):
            return 'INVALID_MONEY_VALUE'
    else:
        bounds = amount.get('range')
        if (not isinstance(bounds, Mapping) or not numeric(bounds.get('min')) or not numeric(bounds.get('max'))
                or bounds.get('min_op') not in ('>=', '>') or bounds.get('max_op') not in ('<=', '<')
                or bounds['min'] > bounds['max'] or (bounds['min'] == bounds['max']
                    and (bounds['min_op'] == '>' or bounds['max_op'] == '<'))):
            return 'INVALID_MONEY_RANGE'
    if raw:
        source = normalize_slot_money(raw)
        if source['parse_status'] != 'success':
            return source['parse_notes']
        if any(source.get(k) != amount.get(k) for k in ('value', 'unit', 'op', 'range')):
            return 'MONEY_VALUE_NOT_FROM_SOURCE'
    return None
