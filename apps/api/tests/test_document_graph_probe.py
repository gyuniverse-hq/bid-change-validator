"""제품 그래프/직렬화/판정/비교 함수를 실행한다. 모델과 입력은 합성이다."""
import copy
from dataclasses import replace
from datetime import date
import json

from apps.api.app.scripts.check_qualification_repeatability import (
    BudgetedExtractor, CapturedCase, measure, digest, CLI_DEFAULT_STRATEGIES,
)
from apps.api.app.ai.qualification.extraction.analysis_pipeline import QualificationAnalysisInput
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot
from apps.api.tests.test_document_graph_comparison import GraphModel


def captured(two_versions=True):
    versions = []
    for n, region in ([(1,'서울특별시'),(2,'부산광역시')] if two_versions else [(2,'부산광역시')]):
        source = QualificationAnalysisInput(notice_id='synthetic', notice_version_id=f'v{n}', documents=[{
            'document_id':f'doc{n}', 'file_sha256':'a'*64, 'extracted_text_sha256':'b'*64,
            'extracted_blocks':[{'block_index':0, 'text':f'{region}에 소재한 업체'}]}])
        versions.append({'role':'baseline' if n == 1 else 'current', 'input':source,
            'input_sha256':digest(source.model_dump(mode='json')), 'notice_date':None,
            'source_documents':[{'id':f'doc{n}', 'name':'합성.txt', 'source_field':'notice', 'status':'EXTRACTED'}]})
    profile = CompanyProfileSnapshot(company_id='SYNTHETIC-COMPANY', region_name='서울특별시', completeness={'region':True})
    return CapturedCase('SYNTHETIC-CASE','SYNTHETIC-NOTICE',profile,tuple(versions))


def test_product_graph_path_repeat_and_version_change_comparisons():
    source = captured(); model = GraphModel()
    report = measure(source, reference_date=date(2026,9,15), extractor=BudgetedExtractor(model,20),
                     runs=2, strategies=('document_graph_v1',))
    assert len(report['rows']) == 4
    assert all(r['execution']=='RETURNED' for r in report['rows']), report['rows']
    assert all(r['analysis_status']=='SUCCEEDED' and r['source_complete'] for r in report['rows'])
    assert [r['notice_overall_status'] for r in report['rows']] == ['eligible','ineligible']*2
    assert len(report['comparisons']) == 4
    for c in report['comparisons']:
        expected = {'UNCHANGED':1} if c['mode']=='SAME_VERSION_REPEAT' else {'MODIFIED':1}
        assert c['counts'] == expected and not c['eligibility_change_asserted']
    assert all(s['same_semantics'] and s['same_judgments'] for s in report['summary'])
    text = json.dumps(report, ensure_ascii=False)
    assert '서울특별시' not in text and '부산광역시' not in text and 'SYNTHETIC-COMPANY' not in text
    assert '합성.txt' not in text
    assert report['quality_verdict']=='NOT_ESTABLISHED' and not report['db_writes']
    assert 'document_graph_v1' in CLI_DEFAULT_STRATEGIES


def test_product_path_requires_real_document_manifest():
    source = captured(False)
    source = replace(source, versions=({k:v for k,v in source.versions[0].items() if k != 'source_documents'},))
    model = GraphModel()
    report = measure(source, reference_date=date(2026,9,15), extractor=BudgetedExtractor(model,20),
                     runs=2, strategies=('document_graph_v1',))
    assert all(r['error_code']=='DOCUMENT_MANIFEST_REQUIRED' for r in report['rows'])
    assert not model.calls


def test_document_failure_does_not_become_eligible():
    source = captured(False)
    version = copy.deepcopy(source.versions[0])
    version['source_documents'].append({'id':'missing','name':'missing','status':'FAILED'})
    source = replace(source, versions=(version,))
    report = measure(source, reference_date=date(2026,9,15), extractor=BudgetedExtractor(GraphModel(),20),
                     runs=2, strategies=('document_graph_v1',))
    assert all(r['analysis_status']=='PARTIAL' and not r['source_complete'] for r in report['rows'])
    assert all(r['notice_overall_status']=='insufficient_data' for r in report['rows'])


def test_single_version_never_fabricates_baseline():
    report = measure(captured(False), reference_date=date(2026,9,15), extractor=BudgetedExtractor(GraphModel(),20),
                     runs=2, strategies=('document_graph_v1',))
    assert len(report['comparisons'])==1 and report['comparisons'][0]['mode']=='SAME_VERSION_REPEAT'
