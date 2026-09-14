import struct
import pytest
from apps.api.app.services.document_extraction import _decode_hwp_paragraph


def control(code, payload=b'\0' * 12):
    return struct.pack('<H', code) + payload + struct.pack('<H', code)


def test_binary_control_ids_are_not_text_and_korean_survives():
    payload = control(2, b'dces' + b'\0' * 8) + '조건 1227 '.encode('utf-16le') + control(11, b' lbt' + b'\0' * 8)
    payload += '단, 법적 허가·장비 예외 漢字 😀'.encode('utf-16le') + struct.pack('<H',13)
    assert _decode_hwp_paragraph(payload) == '조건 1227 단, 법적 허가·장비 예외 漢字 😀\n'


def test_tabs_hyphens_and_spaces_keep_word_boundaries():
    payload = '앞'.encode('utf-16le') + control(9) + '뒤'.encode('utf-16le') + struct.pack('<HHH',24,30,31)
    assert _decode_hwp_paragraph(payload) == '앞\t뒤-  '


@pytest.mark.parametrize('payload', [b'x', struct.pack('<H',2), struct.pack('<H',2) + b'x' * 14])
def test_incomplete_controls_fail_instead_of_silently_dropping_conditions(payload):
    with pytest.raises(ValueError): _decode_hwp_paragraph(payload)
