"""번호 밀착·기호 목록의 합성 회귀. 실제 공고/회사 자료는 저장하지 않는다."""
import gzip
import json
from pathlib import Path

import pytest

from apps.api.app.ai.qualification.extraction.review_plan import (
    LEGACY_PLAN_VERSION, PLAN_VERSION, build_review_inventory, plan_review_requests,
)
from apps.api.app.qualification.graph.document import GraphError, validate_snapshot, fingerprint
from apps.api.app.qualification.graph.comparison import compare_document_graphs
from apps.api.tests.test_document_graph_comparison import make

SYNTHETIC = """3
참가자격
○ 아래 등록 요건을 모두 충족해야 한다.
1)「합성 규정」에 따른 처리업(1001) 또는 재활용업(1002) 등록업체
2)「합성 규정」에 따른 운반업(2001) 등록업체
※ 단, 필요한 장비 조건에 따라 별도 등록을 요구하지 않을 수 있다.
○ 주된 영업소의 소재지는 시험지역이어야 한다.
○ 본 용역은 사전 확인서를 제출한 업체에 한하여
입찰 참가를 인정한다.
4
현장 방문
○ 방문 전 담당자와 협의한다.
"""


def inventory(text=SYNTHETIC, version=PLAN_VERSION):
    return build_review_inventory([{'document_id':'SYNTHETIC', 'block_index':0, 'text':text}],
                                  notice_version_id='test-version', plan_version=version)


@pytest.mark.parametrize('symbol', ['○','●','□','■','◎'])
@pytest.mark.parametrize('space', ['', ' '])
def test_bullet_not_swallowed_by_preceding_note(symbol, space):
    inv = inventory(f'※ 설명이다.\n{symbol}{space}확인할 조건이다.')
    assert [u.kind for u in inv.units] == ['NOTE','CLAUSE']
    assert inv.units[1].marker == symbol


@pytest.mark.parametrize('marker', ['1)','(1)','가)'])
@pytest.mark.parametrize('opening', ['「규정」','등록','ISO'])
def test_attached_numbering_starts_a_clause(marker, opening):
    text = f'※ 설명\n{marker}{opening} 조건\n○ 다른 조건'
    inv = inventory(text)
    assert len(inv.units) == 3 and inv.units[1].marker == marker
    assert inv.units[1].kind == 'CLAUSE'
    assert ''.join(u.candidate.text for u in inv.units) == text


@pytest.mark.parametrize('text', ['1.3억원 이상','12년 이상','1450 등록업체','2026.09.15','1\n수량'])
def test_numbers_and_unknown_titles_are_not_guessed_as_headings(text):
    inv = inventory(text)
    assert len(inv.units) == 1 and inv.units[0].kind == 'UNMARKED'


@pytest.mark.parametrize('title', ['참가자격','입찰 참가 자격','현장 방문','입찰서 제출'])
def test_number_and_known_title_on_separate_lines(title):
    inv = inventory(f'3\n{title}\n○ 등록 조건')
    assert len(inv.units) == 2 and inv.units[0].marker == '3'
    assert inv.units[0].candidate.candidate_id in inv.units[1].ancestor_ids


@pytest.mark.parametrize('newline', ['\n','\r\n'])
def test_conditions_and_notes_have_separate_exact_ranges(newline):
    text = SYNTHETIC.replace('\n', newline)
    inv = inventory(text)
    assert [u.marker for u in inv.units] == ['3','○','1)','2)',None,'○','○','4','○']
    assert ''.join(u.candidate.text for u in inv.units) == text
    for u in inv.units:
        c = u.candidate
        assert text[c.start_offset:c.end_offset] == c.text
    industry = next(u for u in inv.units if '1001' in u.candidate.text)
    transport = next(u for u in inv.units if '2001' in u.candidate.text)
    note = next(u for u in inv.units if u.kind == 'NOTE')
    region = next(u for u in inv.units if '시험지역' in u.candidate.text)
    assert industry.kind == transport.kind == region.kind == 'CLAUSE'
    assert industry.candidate.candidate_id != transport.candidate.candidate_id
    assert '시험지역' not in note.candidate.text
    assert transport.candidate.candidate_id not in region.ancestor_ids
    assert industry.ancestor_ids == transport.ancestor_ids
    visit = next(u for u in inv.units if '사전 확인서' in u.candidate.text)
    assert '입찰 참가를 인정한다.' in visit.candidate.text
    assert inv.units[-1].section_id != visit.section_id


def test_retry_preserves_version_identity_and_parent_context():
    inv = inventory()
    key = next(u.candidate.candidate_id for u in inv.units if '2001' in u.candidate.text)
    plan = plan_review_requests(inv, target_candidate_ids=[key])
    assert plan.manifest()['plan_version'] == PLAN_VERSION
    assert plan.target_candidate_ids == (key,)
    request = json.loads(plan.requests[0].body)
    assert any('아래 등록 요건' in s['text'] for s in request['sources'])
    assert any('요구하지 않을 수' in s['text'] for s in request['sources'])
    assert request['target_candidate_ids'] == [key]


def old_snapshot():
    path = Path(__file__).parent/'fixtures/qualification_graph_plan_v1.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


def rehash(s):
    s['snapshot_sha256'] = fingerprint({k:v for k,v in s.items() if k != 'snapshot_sha256'})
    return s


def test_previously_generated_v1_snapshot_still_loads():
    stored = old_snapshot()
    assert stored['snapshot_sha256'] == 'e60c8ed527a87044e8d40bfe4397c52db21200ab2f1b697a29409d8cac1cb439'
    source, inv, decisions = validate_snapshot(stored)
    assert inv.plan_version == LEGACY_PLAN_VERSION and source.notice_version_id == 'v1'
    assert set(decisions) == {u.candidate.candidate_id for u in inv.units}


def test_mixed_plan_versions_are_not_notice_changes():
    old = old_snapshot()
    new = make('서울특별시에 소재한 업체', version='v2', docid='doc2')
    compared = compare_document_graphs(old, new)
    assert compared['same_source_text']
    assert compared['comparison_status'] == 'REVIEW_REQUIRED'
    assert 'CANDIDATE_PLAN_CHANGED' in compared['issues']
    assert compared['relation_change'] == 'REVIEW_REQUIRED'
    assert not ({'ADDED','REMOVED','MODIFIED'} & set(compared['counts']))


@pytest.mark.parametrize('version', ['unrecognized',None,2])
def test_saved_unknown_version_never_falls_back_to_latest(version):
    s = old_snapshot(); s['audit']['plan']['plan_version'] = version
    with pytest.raises(GraphError, match='UNSUPPORTED_SNAPSHOT_PLAN_VERSION'):
        validate_snapshot(rehash(s))


def test_missing_saved_version_is_an_error():
    s = old_snapshot(); del s['audit']['plan']['plan_version']
    with pytest.raises(GraphError, match='MISSING_SNAPSHOT_PLAN_VERSION'):
        validate_snapshot(rehash(s))


def test_changing_version_metadata_does_not_reinterpret_old_ids():
    s = old_snapshot(); s['audit']['plan']['plan_version'] = PLAN_VERSION
    with pytest.raises(GraphError, match='GRAPH_INVENTORY_INTEGRITY'):
        validate_snapshot(rehash(s))


def test_stored_plan_must_match_source_inventory():
    s = old_snapshot(); s['audit']['plan']['input_blocks_sha256'] = '0'*64
    with pytest.raises(GraphError, match='SAVED_PLAN_BASIS_MISMATCH'):
        validate_snapshot(rehash(s))


def test_unknown_runtime_version_is_rejected():
    with pytest.raises(ValueError, match='UNSUPPORTED_REVIEW_PLAN_VERSION'):
        inventory(version='not-a-supported-version')
