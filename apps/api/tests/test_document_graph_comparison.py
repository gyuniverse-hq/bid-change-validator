"""실제 그래프 추출/직렬화/판정/비교. 모델 I/O와 입력은 합성이며 실측이 아니다."""
import copy
import json
import re
from datetime import date
import pytest
from apps.api.app.ai.qualification.extraction.analysis_pipeline import QualificationAnalysisInput
from apps.api.app.ai.qualification.extraction.review_execution import ReviewOptions
from apps.api.app.qualification.rules.judgment import CompanyProfileSnapshot
from apps.api.app.qualification.graph import document as doc
from apps.api.app.qualification.graph.comparison import compare_document_graphs
from apps.api.app.qualification.graph.judgment import judge_document_graph

DAY=date(2026,9,15)


class GraphModel:
    model='synthetic-no-network'
    def __init__(self,omit=None,non_requirement=None,relation='ALL_OF'):
        self.calls=[];self.omit=omit;self.non_requirement=non_requirement;self.relation=relation
    def __call__(self,prompt,body,schema):
        p=json.loads(body);self.calls.append((schema['name'],p))
        if schema['name']=='qualification_document_relations_v1':
            ids=p['required_candidate_ids']
            nodes=[{'id':f'n{i}','operator':'CLAUSE','candidate_id':k,'children':[],'scope_candidate_ids':[],'evidence':[]} for i,k in enumerate(ids)]
            if len(ids)==1:return {'status':'COMPLETE','reason':None,'root_id':'n0','nodes':nodes}
            nodes.append({'id':'root','operator':self.relation,'candidate_id':None,'children':[n['id'] for n in nodes],
                'scope_candidate_ids':[s['candidate_id'] for s in p['sources']],
                'evidence':[{'candidate_id':s['candidate_id'],'quote':s['text']} for s in p['sources']]})
            return {'status':'COMPLETE','reason':None,'root_id':'root','nodes':nodes}
        sources={s['candidate_id']:s for s in p['sources']};rows=[]
        for key in p['target_candidate_ids']:
            text=sources[key]['text']
            if self.omit and self.omit in text:continue
            row={'candidate_id':key,'status':'REQUIREMENT','reason':None,'basis':'SELF_CONTAINED','role':'mandatory','atoms':[],'nodes':[],'root_id':'n'}
            if (self.non_requirement and self.non_requirement in text) or not any(x in text for x in ('업종코드','소재','실적')):
                row.update(status='NOT_REQUIREMENT',reason='합성 안내',root_id=None);rows.append(row);continue
            if '업종코드' in text:t,r,v='INDUSTRY','INDUSTRY_CODE',re.search(r'업종코드 (\d{4})',text).group(1)
            elif '실적' in text:t,r,v='PERFORMANCE_AMOUNT','PERFORMANCE_AMOUNT',re.search(r'(?:[\d,.]+억|[\d,.]+천만)원 이상',text).group(0)
            else:t,r,v='REGION','REGION_NAME',re.search(r'서울특별시|부산광역시|전북특별자치도',text).group(0)
            src=lambda q:{'source_candidate_id':key,'quote':q}
            atom={'atom_id':'a','type':t,'subject':'BIDDER','predicate_source':src(text),'value_role':r,
                'value_source':src(v),'qualifiers':[],'aggregation':'UNSPECIFIED','aggregation_source':None}
            if t=='PERFORMANCE_AMOUNT':atom.update(aggregation='MAX',aggregation_source=src('단일'))
            row.update(atoms=[atom],nodes=[{'node_id':'n','operator':'ATOM','atom_id':'a','children':[],'evidence':[]}]);rows.append(row)
        return {'decisions':rows}


def make(text='업종코드 1257 등록 업체',version='v1',docid='doc1',notice='notice1',model=None,missing_doc=False):
    source=QualificationAnalysisInput(notice_id=notice,notice_version_id=version,documents=[{'document_id':docid,
        'file_sha256':'a'*64,'extracted_text_sha256':'b'*64,'extracted_blocks':[{'block_index':0,'page':1,'text':text}]}])
    manifest=[{'id':docid,'name':'합성 공고.txt','source_field':'notice','status':'EXTRACTED'}]
    if missing_doc:manifest.append({'id':'failed','name':'누락.txt','source_field':'spec','status':'FAILED'})
    return doc.extract_document_graph(source,structured_extract=model or GraphModel(),document_manifest=manifest,options=ReviewOptions(max_calls=10))


def rehash(s):
    s['snapshot_sha256']=doc.fingerprint({k:v for k,v in s.items() if k!='snapshot_sha256'});return s


def test_source_only_extraction_roundtrip():
    m=GraphModel();s=make(model=m);saved=json.loads(json.dumps(s))
    assert doc.graph_status(saved)=='SUCCEEDED'
    assert 'company_id' not in json.dumps(m.calls)
    assert doc.validate_snapshot(saved)[2].keys()==doc.validate_snapshot(s)[2].keys()


def test_company_changes_do_not_require_model():
    m=GraphModel();s=make('서울특별시에 소재한 업체',model=m);calls=len(m.calls)
    for region,status in [('서울특별시','eligible'),('부산광역시','ineligible')]:
        p=CompanyProfileSnapshot(company_id=region,region_name=region,completeness={'region':True})
        assert judge_document_graph(s,p,case_id='C',reference_date=DAY)['overall_status']==status
    assert len(m.calls)==calls


def test_cross_clause_and_preserved_after_storage():
    s=make('3. 다음 요건을 모두 충족\n가. 업종코드 1257 등록 업체\n나. 서울특별시에 소재한 업체')
    assert doc.graph_status(s)=='SUCCEEDED',s['composition']
    p=CompanyProfileSnapshot(company_id='C',region_name='부산광역시',industries=[{'code':'1257','name':'시험'}],completeness={'region':True,'industries':True})
    assert judge_document_graph(json.loads(json.dumps(s)),p,case_id='C',reference_date=DAY)['overall_status']=='ineligible'


def test_discretion_exception_is_not_automatic_exemption():
    text='3. 모두 조건\n가. 업종코드 1257 등록 업체\n나. 업종코드 1227 등록 업체\n※ 나 조건이면 가 조건을 요구하지 않을 수 있다.'
    s=make(text,model=GraphModel(relation='EXEMPT_IF'))
    assert 'DISCRETION_IS_NOT_AUTOMATIC_EXEMPTION' in s['composition']['pending_codes']
    possible=make(text,model=GraphModel(relation='POSSIBLE_EXEMPT_IF'))
    assert possible['composition']['status']=='COMPLETE'
    _,_,decisions=doc.validate_snapshot(possible)
    ids={json.loads(d.atoms[0].requirement_json)['value']:k for k,d in decisions.items() if d.atoms}
    nodes=possible['composition']['nodes'];root=next(n for n in nodes if n['id']=='root')
    root['children']=[next(n['id'] for n in nodes if n['candidate_id']==ids[v]) for v in ['1257','1227']];rehash(possible)
    p=CompanyProfileSnapshot(company_id='C',industries=[{'code':'1227','name':'시험'}],completeness={'industries':True})
    assert judge_document_graph(possible,p,case_id='C',reference_date=DAY)['overall_status']=='insufficient_data'


def test_missing_source_document_blocks_overall_eligible():
    s=make('서울특별시에 소재한 업체',missing_doc=True)
    assert doc.graph_status(s)=='PARTIAL'
    p=CompanyProfileSnapshot(company_id='C',region_name='서울특별시',completeness={'region':True})
    assert judge_document_graph(s,p,case_id='C',reference_date=DAY)['overall_status']=='insufficient_data'


def test_same_source_with_new_version_and_ids_is_unchanged():
    r=compare_document_graphs(make(),make(version='v2',docid='doc2'))
    assert r['same_source_text'] and r['counts']=={'UNCHANGED':1} and r['relation_change']=='UNCHANGED'


def test_amount_change_is_modified_not_remove_add():
    r=compare_document_graphs(make('단일 5천만원 이상 실적'),make('단일 1억원 이상 실적',version='v2',docid='doc2'))
    assert r['counts']=={'MODIFIED':1}
    assert r['changes'][0]['before']['meaning']['predicates'][0]['value']==50_000_000
    assert r['changes'][0]['after']['meaning']['predicates'][0]['value']==100_000_000
    assert not r['eligibility_change_asserted']


def test_same_source_missing_extraction_is_not_requirement_removed():
    text='3. 모두 충족\n가. 업종코드 1257 등록 업체\n나. 서울특별시에 소재한 업체'
    r=compare_document_graphs(make(text),make(text,version='v2',model=GraphModel(omit='업종코드')))
    assert r['counts'].get('ANALYSIS_INCONSISTENCY')==1 and not r['counts'].get('REMOVED')
    assert r['comparison_status']=='REVIEW_REQUIRED'


def test_same_source_wrong_nonrequirement_is_inconsistency():
    r=compare_document_graphs(make('서울특별시에 소재한 업체'),make('서울특별시에 소재한 업체',version='v2',model=GraphModel(non_requirement='서울')))
    assert r['counts']=={'ANALYSIS_INCONSISTENCY':1}


def test_actual_source_deletion_and_incomplete_source_distinguished():
    a=make('3. 모두 충족\n가. 업종코드 1257 등록 업체\n나. 서울특별시에 소재한 업체')
    b=make('3. 모두 충족\n가. 업종코드 1257 등록 업체',version='v2')
    assert compare_document_graphs(a,b)['counts'].get('REMOVED')==1
    c=make('3. 모두 충족\n가. 업종코드 1257 등록 업체',version='v2',missing_doc=True)
    assert not compare_document_graphs(a,c)['counts'].get('REMOVED')


def test_reordered_clauses_are_not_added_or_removed():
    a=make('3. 모두 충족\n가. 업종코드 1257 등록 업체\n나. 서울특별시에 소재한 업체')
    b=make('3. 모두 충족\n나. 서울특별시에 소재한 업체\n가. 업종코드 1257 등록 업체',version='v2')
    r=compare_document_graphs(a,b)
    assert all(row['change_type']=='UNCHANGED' for row in r['changes']) and r['relation_change']=='UNCHANGED'


def test_many_to_many_edit_is_not_forced_alignment():
    a=make('3. 모두 충족\n가. 업종코드 1257 등록 업체\n나. 업종코드 1227 등록 업체')
    b=make('3. 모두 충족\n다. 업종코드 6770 등록 업체\n라. 업종코드 6786 등록 업체',version='v2')
    r=compare_document_graphs(a,b)
    assert r['counts'].get('REVIEW_REQUIRED')==4 and not r['counts'].get('ADDED')


def test_relationship_edit_detected_separately():
    a=make('3. 아래 조건을 모두 충족\n가. 업종코드 1257 등록 업체\n나. 업종코드 1227 등록 업체')
    b=make('3. 아래 조건 중 하나 충족\n가. 업종코드 1257 등록 업체\n나. 업종코드 1227 등록 업체',version='v2',model=GraphModel(relation='ANY_OF'))
    assert compare_document_graphs(a,b)['relation_change']=='RELATION_CHANGED'


def test_same_source_relationship_variation_is_inconsistency():
    text='3. 아래 조건을 모두 또는 중 하나 충족\n가. 업종코드 1257 등록 업체\n나. 업종코드 1227 등록 업체'
    assert compare_document_graphs(make(text),make(text,version='v2',model=GraphModel(relation='ANY_OF')))['relation_change']=='ANALYSIS_INCONSISTENCY'


@pytest.mark.parametrize('edit',[
    lambda s:s['decisions'][0]['sources'][0].update(quote='없는 문구'),
    lambda s:s['decisions'][0]['graph']['nodes'][0].update(atom_id='absent'),
    lambda s:s['source'].update(notice_version_id='foreign'),
    lambda s:s['composition']['nodes'][0].update(candidate_id='foreign'),
    lambda s:s['decisions'].append(copy.deepcopy(s['decisions'][0])),
    lambda s:s['decisions'][0].update(extra_field='ignored'),
])
def test_rehashed_corruption_not_silently_accepted(edit):
    s=make();edit(s);rehash(s)
    with pytest.raises(doc.GraphError):doc.validate_snapshot(s)


def test_snapshot_hash_is_mandatory():
    s=make();s['calls']+=1
    with pytest.raises(doc.GraphError):doc.validate_snapshot(s)


def test_other_notice_rejected():
    with pytest.raises(doc.GraphError):compare_document_graphs(make(),make(notice='different'))


def test_date_cannot_default_to_today():
    with pytest.raises(doc.GraphError):judge_document_graph(make(),CompanyProfileSnapshot(company_id='C'),case_id='C',reference_date=None)


def test_budget_includes_relation_model_call():
    source=QualificationAnalysisInput(notice_id='N',notice_version_id='V',documents=[{'document_id':'D','extracted_blocks':[{'block_index':0,'text':'3. 모두 충족\n가. 업종코드 1257 등록 업체\n나. 서울특별시에 소재한 업체'}]}])
    m=GraphModel();s=doc.extract_document_graph(source,structured_extract=m,document_manifest=[{'id':'D','name':'공고','status':'EXTRACTED'}],options=ReviewOptions(max_calls=1))
    assert len(m.calls)==1 and 'RELATION_CALL_BUDGET' in s['composition']['pending_codes']


def test_empty_source_is_failed():
    source=QualificationAnalysisInput(notice_id='N',notice_version_id='V',documents=[])
    assert doc.graph_status(doc.extract_document_graph(source,structured_extract=GraphModel(),document_manifest=[]))=='FAILED'
