from apps.api.app.copilot.answer_validation import generated_draft, verify
from apps.api.app.copilot.v31_contracts import Verdicts


def test_requirement_exclusion_is_bound_to_its_exact_current_source():
    from apps.api.tests.test_copilot_v31 import bundle
    from apps.api.app.copilot.submission_obligations import preserve_requirement_exclusions
    b=bundle();fact=b.facts[0];fact.origin_tool='READ_JUDGMENT';fact.requirement_key='experience'
    source=next(s for s in b.sources if s.source_id in fact.source_ids)
    source.kind='DOCUMENT';source.quote='최근 4년 내 행사 운영 실적(축제, 체육대회 제외)'
    text='최근 4년 행사 운영 실적 요건을 확인해야 합니다.'
    preserved=preserve_requirement_exclusions(text,[fact.fact_id],b)
    assert '축제, 체육대회 제외' in preserved
    assert preserve_requirement_exclusions(preserved,[fact.fact_id],b)==preserved
    assert preserve_requirement_exclusions(text,[b.facts[1].fact_id],b)==text
    source.scope=source.scope.model_copy(update={'analysis_run_id':None})
    assert preserve_requirement_exclusions(text,[fact.fact_id],b)==text
from apps.api.tests.test_copilot_answer_progress import setup


def test_annex_citation_includes_its_owning_submission_clause_only_in_same_document():
    from uuid import uuid4
    from apps.api.app.copilot.submission_obligations import expand_submission_references
    from apps.api.app.copilot.v31_contracts import Fact, Source
    _,bundle,_=setup()
    doc=str(uuid4())
    bundle.sources[1].document_id=doc
    bundle.sources[1].quote='<별첨 1> 제출 자료 목록\n서약서\n1'
    for fid,document in [('parent',doc),('other-document',str(uuid4()))]:
        bundle.sources.append(Source(source_id=fid,kind='DOCUMENT',document_id=document,
            scope=bundle.scope,quote='나. 제안서 제출\n제출서류 : <별첨 1>의 순서로 제출 요망'))
        bundle.facts.append(Fact(fact_id=fid,kind='NOTICE_FACT',text='제안서 제출',
            origin_tool='READ_DOCUMENT',source_ids=[fid],scope=bundle.scope))
    assert expand_submission_references(['document'],bundle)==['document','parent']
    assert expand_submission_references(['judgment'],bundle)==['judgment']
    bundle.sources[1].document_id=None
    assert expand_submission_references(['document'],bundle)==['document']


def test_explicit_annex_reference_preserves_same_document_at_registration_and_contract():
    from uuid import uuid4
    from apps.api.app.copilot.submission_obligations import referenced_stage_obligations
    from apps.api.app.copilot.v31_contracts import Fact,Source
    _,bundle,_=setup();doc=str(uuid4())
    bundle.sources[1].document_id=doc
    bundle.sources[1].quote='앞 절의 끝\n<별첨 1> 제출 자료 목록\n보안 준수 서약서\n1\n[별지 제4호 서식]'
    bundle.sources.append(Source(source_id='parent',kind='DOCUMENT',document_id=doc,scope=bundle.scope,
        quote='나. 제안서 제출\n제출서류: <별첨 1>의 순서로 제출 요망'))
    bundle.facts.append(Fact(fact_id='parent',kind='NOTICE_FACT',origin_tool='READ_DOCUMENT',
        text='제안서 제출',source_ids=['parent'],scope=bundle.scope))
    anchor={'document':'보안 준수 서약서','stage':'계약체결','fact_ids':['contract']}
    result=referenced_stage_obligations(bundle,[anchor])
    assert result==[dict(document='보안 준수 서약서',stage='입찰참가등록',fact_ids=['document','parent'])]
    assert referenced_stage_obligations(bundle,[dict(anchor,document='다른 확인서')])==[]
    original=bundle.sources[1].quote
    bundle.sources[1].quote='계약체결 시 보안 준수 서약서를 제출해야 한다.\n<별첨 1> 제출 자료 목록\n다른 확인서\n1\n[별지 제3호 서식]'
    assert referenced_stage_obligations(bundle,[anchor])==[]
    bundle.sources[1].quote=original
    bundle.sources[-1].document_id=str(uuid4())
    assert referenced_stage_obligations(bundle,[anchor])==[]


def test_two_stages_survive_and_all_row_fields_reach_verifier():
    _, bundle, _ = setup()
    from apps.api.app.copilot.evidence_payload import evidence_payload
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            if stage == 'generate':
                rows = []
                for i, phase in enumerate(['입찰 등록', '계약체결']):
                    rows.append(dict(claim_id=str(i), text='표시되면 안 되는 미검증 중복 설명', fact_ids=['F2'],
                        speech_act='ASSERTION', submission=dict(document='안전보건 서약서', stage=phase,
                        obligation='필수', deadline='원문 미기재', method='방문', timing='시점 미확정',
                        conditions='두 단계의 의무를 각각 확인; 원문이 명시한 업종 등록과 현장 방문 조건')) )
                return schema.model_validate({'claims': rows})
            self.verified = body['claims']
            return Verdicts(verdicts=[dict(claim_id=c['claim_id'], status='CONTRADICTED', reason='방법 근거 없음') for c in body['claims']])
    gateway = Gateway()
    draft = generated_draft(gateway, 'generate', '', {'tasks': [{'kind': 'READ_DOCUMENT'}],
                            'evidence': evidence_payload(bundle)}, bundle)
    assert len(draft.claims) == 2
    assert '입찰 등록' in draft.claims[0].text and '계약체결' in draft.claims[1].text
    claims, _ = verify(draft, bundle, gateway)
    for row in gateway.verified:
        assert all(t in row['text'] for t in ['안전보건 서약서', '필수', '원문 미기재', '방문', '시점 미확정', '두 단계'])
        assert '미검증 중복 설명' not in row['text']
        assert '업종 등록과 현장 방문 조건' in row['text']
        assert '업종 등록 → 현장 방문' not in row['text']
    assert all(c.validation == 'CONTRADICTED' for c in claims)
    assert all(c.submission is not None for c in claims)


def test_guarantee_expiry_is_preserved_without_inventing_a_date_or_resolving_conflicts():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation, preserve_guarantee_validity
    row = SubmissionObligation(document='입찰보증보험증권',stage='입찰',obligation='필수',
        deadline='2026년 7월 27일 14:00',method='전자보증서',timing='예정일 경과',
        conditions='5% 이상',stage_kind='가격입찰',deadline_kind='절대일시')
    quote = '※ 보증기간의 만료일은 입찰서 제출마감일의 다음날부터 30일 이후일 것'
    preserved = preserve_guarantee_validity(row,[quote])
    assert quote[2:] in preserved.conditions and preserved.deadline == row.deadline
    assert preserve_guarantee_validity(preserved,[quote]) == preserved
    assert preserve_guarantee_validity(row,[quote,quote.replace('30일','60일')]) == row
    other = row.model_copy(update={'document':'영업신고증'})
    assert preserve_guarantee_validity(other,[quote]) == other


def test_freshness_anchor_cannot_be_marked_complete_by_merely_citing_its_source():
    from apps.api.app.copilot.submission_obligations import explicit_validity_conditions
    from apps.api.app.copilot.acceptance import freeze_acceptance, assess_acceptance
    from apps.api.app.copilot.v31_contracts import Claim
    _,bundle,plan=setup()
    bundle.sources[1].quote='- 4대 보험 중 어느 하나의 가입증명 자료(최근 3개월 이내)\n최근 2년 사업실적'
    plan.goal='제출 서류와 준비 체크리스트를 만들어줘'
    anchors=explicit_validity_conditions(bundle,plan.goal)
    assert len(anchors)==1 and anchors[0]['term']=='최근 3개월 이내'
    assert explicit_validity_conditions(bundle,'업종을 알려줘')==[]
    criteria=tuple(c for c in freeze_acceptance(plan,bundle) if c.source_required_terms)
    claim=Claim(claim_id='c',text='가입증명 자료를 제출합니다.',fact_ids=['document'],source_ids=['document'],
        validation='SUPPORTED',method='semantic')
    verdict=Verdicts(verdicts=[],criteria=[dict(criterion_id=criteria[0].criterion_id,
        status='MET',claim_ids=['c'],reason='model says complete')])
    assert assess_acceptance(criteria,verdict,[claim])['task_coverage']=='PARTIAL'
    claim.text='4대 보험 중 어느 하나의 가입증명 자료는 최근 3개월 이내의 자료여야 합니다.'
    assert assess_acceptance(criteria,verdict,[claim])['task_coverage']=='COMPLETE'


def test_relative_deadline_cannot_be_marked_elapsed_from_another_planned_event():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation, structural_error
    row = SubmissionObligation(document='보안계획서',stage='선정 후',obligation='조건부',deadline='계약 체결 전',
        method='발주기관 제출',timing='예정일 경과',conditions='선정 업체만',
        stage_kind='선정후',deadline_kind='사건기준',anchor_event='계약 체결')
    assert structural_error(row) == 'RELATIVE_DEADLINE_WITHOUT_CONFIRMED_EVENT'
    assert structural_error(row.model_copy(update={'timing':'시점 미확정'})) is None
    incomplete=row.model_copy(update={'timing':'시점 미확정','document':'제안서 및 공고상 기타 서류'})
    assert structural_error(incomplete)=='UNRESOLVED_DOCUMENT_LIST'
    assert structural_error(incomplete.model_copy(update={'obligation':'확인 필요'})) is None


def test_literal_freshness_pair_survives_omission_but_still_requires_verification():
    from apps.api.app.copilot.submission_obligations import preserve_explicit_validity
    from apps.api.app.copilot.acceptance import freeze_acceptance,assess_acceptance
    from apps.api.app.copilot.v31_contracts import Draft
    _,bundle,plan=setup()
    bundle.sources[1].quote='- 장비 검사 증명서(최근 6개월 이내)'
    plan.goal='제출 서류를 정리해줘'
    criteria=tuple(c for c in freeze_acceptance(plan,bundle) if c.source_required_terms)
    draft=preserve_explicit_validity(Draft(claims=[]),bundle,criteria)
    assert len(draft.claims)==1
    assert '장비 검사 증명서(최근 6개월 이내)' in draft.claims[0].text
    assert draft.claims[0].fact_ids==['document'] and draft.claims[0].source_ids==['document']
    assert preserve_explicit_validity(draft,bundle,criteria)==draft
    assert preserve_explicit_validity(Draft(claims=[]),bundle,()).claims==[]
    class Reject:
        def call(self,stage,prompt,body,schema):
            assert '장비 검사 증명서' in body['claims'][0]['text']
            return Verdicts(verdicts=[dict(claim_id=draft.claims[0].claim_id,status='CONTRADICTED',reason='rejected')])
    claims,_=verify(draft,bundle,Reject())
    verdict=Verdicts(verdicts=[],criteria=[dict(criterion_id=criteria[0].criterion_id,status='MET',
        claim_ids=[draft.claims[0].claim_id],reason='model says complete')])
    assert assess_acceptance(criteria,verdict,claims)['task_coverage']=='PARTIAL'
    # A changed source no longer supplies the old quotation.
    bundle.sources[1].quote='장비 검사 증명서의 유효기간은 확인이 필요합니다.'
    assert preserve_explicit_validity(Draft(claims=[]),bundle,criteria).claims==[]


def test_approval_authority_does_not_prove_submission_recipient():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation,distinguish_submission_recipient
    row=SubmissionObligation(document='장비 증빙',stage='착수',obligation='필수',deadline='착수 전',
        method='품질 관리 담당자에게 제출',timing='시점 미확정',conditions='장비 변경 시 승인 필요')
    approval='착수 전 장비 증빙을 제출한다. 변경 시 품질 관리 담당자의 승인을 받아야 한다.'
    changed=distinguish_submission_recipient(row,[approval])
    assert changed.method.startswith('인용 근거만으로')
    assert changed.document==row.document and changed.deadline==row.deadline
    assert distinguish_submission_recipient(row,[approval+' 품질 관리 담당자에게 제출한다.'])==row
    assert distinguish_submission_recipient(row,['제출처: 품질 관리 담당자'])==row
    # A grouped row cannot transfer one document's recipient to a different
    # document for which the source identifies only a change-approval authority.
    grouped=row.model_copy(update={'document':'작업계획서; 장비 증빙'})
    plan='작업계획서를 작성하여 품질 관리 담당자에게 제출하여야 한다.'
    mixed=distinguish_submission_recipient(grouped,[plan,approval])
    assert plan in mixed.method
    assert '나머지 서류의 제출처' in mixed.method
    assert mixed.document==grouped.document and mixed.conditions==grouped.conditions
    # Even if the model omits the other source, one document's recipient is
    # not evidence for all members. A trailing approval phrase does not help.
    omitted=distinguish_submission_recipient(grouped,[plan])
    assert plan in omitted.method and '나머지 서류의 제출처' in omitted.method
    continued=row.model_copy(update={'method':'품질 관리 담당자에게 제출하고, 변경 시 사전 승인'})
    assert distinguish_submission_recipient(continued,[approval]).method.startswith('인용 근거만으로')
    # Two explicit recipients do not create a missing-recipient warning.
    assert distinguish_submission_recipient(grouped,[plan,approval+' 품질 관리 담당자에게 제출한다.'])==grouped


def test_known_calendar_date_with_unannounced_clock_time_is_not_an_unobserved_event():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation, normalize_event_timing, structural_error
    row=SubmissionObligation(document='발표자료',stage='발표',stage_kind='제안발표',obligation='필수',
        deadline='2026년 7월 30일 예정 발표일(발표 시각은 업체별 개별 통보)',method='방문',
        timing='예정일 경과',conditions='실제 개최 여부는 별도 확인',deadline_kind='사건기준',anchor_event='발표')
    actual=normalize_event_timing(row)
    assert actual.deadline_kind=='절대일시' and actual.anchor_event is None
    assert actual.deadline==row.deadline and actual.conditions==row.conditions
    assert structural_error(actual) is None
    relative=row.model_copy(update={'deadline':'2026년 7월 30일 발표 종료 후 7일, 시각 개별 통보'})
    safe_relative=normalize_event_timing(relative)
    assert safe_relative.deadline==relative.deadline and safe_relative.anchor_event==relative.anchor_event
    assert safe_relative.timing=='시점 미확정' and structural_error(safe_relative) is None


def test_document_sequence_advice_is_verified_without_promoting_company_assumptions():
    from apps.api.app.copilot.evidence_payload import evidence_payload
    _,bundle,_=setup()
    class Gateway:
        fact_citations=True
        def call(self,stage,prompt,body,schema):
            if stage=='generate':
                return schema.model_validate({'claims':[
                    dict(claim_id='order',text='기한 후 제출 순서를 제안합니다.',fact_ids=['F2'],speech_act='CHECK_REQUEST'),
                    dict(claim_id='company',text='회사 확인 순서를 제안합니다.',fact_ids=['F1'],speech_act='ASSUMPTION')]})
            self.seen=body['claims']
            return Verdicts(verdicts=[dict(claim_id=c['claim_id'],status='CONTRADICTED',
                observed_act=c['speech_act'],reason='원문 기한과 충돌') for c in body['claims']])
    gateway=Gateway()
    draft=generated_draft(gateway,'generate','',{'tasks':[{'kind':'READ_DOCUMENT'}],
        'evidence':evidence_payload(bundle)},bundle)
    assert draft.claims[0].speech_act=='ASSERTION'
    assert draft.claims[1].speech_act=='ASSUMPTION'
    claims,_=verify(draft,bundle,gateway)
    assert all(c.validation=='CONTRADICTED' for c in claims)


def test_non_document_generation_keeps_existing_schema():
    _, bundle, _ = setup()
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            assert 'submission' not in str(schema.model_json_schema())
            return schema.model_validate({'claims': []})
    assert not generated_draft(Gateway(), 'generate', '', {'tasks': [{'kind': 'READ_JUDGMENT'}]}, bundle).claims


def test_unobserved_event_timing_is_weakened_before_full_row_verification():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation, normalize_event_timing
    from apps.api.app.copilot.evidence_payload import evidence_payload
    _, bundle, _ = setup()
    row = SubmissionObligation(document='서약서',stage='가격입찰',obligation='조건부',
        deadline='전자입찰서 제출 시',method='전자입찰서로 갈음',timing='예정일 경과',
        conditions='전자입찰인 경우',deadline_kind='사건기준',anchor_event='전자입찰서 제출')
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            if stage == 'generate':
                return schema.model_validate({'claims':[dict(claim_id='row',text='ignored',
                    fact_ids=['F2'],speech_act='ASSERTION',submission=row.model_dump())]})
            self.verified = body['claims'][0]
            return Verdicts(verdicts=[dict(claim_id='row',status='CONTRADICTED',reason='전자 제출 근거 없음')])
    gateway = Gateway()
    draft = generated_draft(gateway,'generate','',{'tasks':[{'kind':'READ_DOCUMENT'}],
        'evidence':evidence_payload(bundle)},bundle)
    claims,_ = verify(draft,bundle,gateway)
    assert gateway.verified['submission']['timing'] == '시점 미확정'
    assert '시점 미확정' in gateway.verified['text'] and '예정일 경과' not in gateway.verified['text']
    assert claims[0].validation == 'CONTRADICTED'
    assert row.timing == '예정일 경과'  # original proposal is not mutated
    undated=row.model_copy(update={'deadline':'검수 완료 후; 구체적 날짜 미기재',
        'deadline_kind':'미기재','anchor_event':'검수 완료'})
    preserved=normalize_event_timing(undated)
    assert preserved.deadline_kind=='사건기준' and preserved.timing=='시점 미확정'
    assert preserved.anchor_event=='검수 완료' and preserved.deadline==undated.deadline
    for update in [{'deadline':'2026년 7월 23일 전자입찰 시'}, {'deadline':'7/23 제출 시'}]:
        candidate = row.model_copy(update=update)
        actual=normalize_event_timing(candidate)
        assert actual.timing=='시점 미확정' and actual.deadline==candidate.deadline
    for update in [{'deadline_kind':'절대일시'}, {'anchor_event':None}]:
        candidate = row.model_copy(update=update)
        assert normalize_event_timing(candidate) == candidate


def test_named_document_counts_survive_generation_without_resolving_conflicting_counts():
    from apps.api.app.copilot.evidence_payload import evidence_payload
    from apps.api.app.copilot.submission_obligations import preserve_document_quantities
    _, bundle, _ = setup()
    bundle.sources[1].quote='제안서 및 (필요시)요약본\n제안서 6부\n(요약본 3부)\nUSB 2매 별도 제출\n신청서 1부'
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            if stage == 'generate':
                return schema.model_validate({'claims':[dict(claim_id='docs',text='ignored',fact_ids=['F2'],
                    speech_act='CHECK_REQUEST',submission=dict(document='제안서 및 필요시 요약본, USB',
                    stage='입찰참가등록',obligation='필수',deadline='원문 미기재',method='방문',
                    timing='시점 미확정',conditions='요약본은 필요시 제출'))]})
            self.claim=body['claims'][0]
            return Verdicts(verdicts=[dict(claim_id='docs',status='CONTRADICTED',reason='방문 제출 근거 없음')])
    gateway=Gateway()
    draft=generated_draft(gateway,'generate','',{'tasks':[{'kind':'READ_DOCUMENT'}],
        'evidence':evidence_payload(bundle)},bundle)
    claims,_=verify(draft,bundle,gateway)
    assert gateway.claim['speech_act']=='ASSERTION'
    for token in ['제안서 6부','요약본 3부','USB 2매']:
        assert token in gateway.claim['text']
    assert '신청서 1부' not in gateway.claim['text']
    assert '요약본 제출 조건: 필요시' in gateway.claim['text']
    assert claims[0].validation=='CONTRADICTED'
    row=draft.claims[0].submission.model_copy(update={'conditions':'별도 확인'})
    assert preserve_document_quantities(row,['제안서 6부','제안서 8부']) == row


def test_form_identity_uses_exact_item_not_the_shared_oath_suffix():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation, preserve_form_identity
    row=SubmissionObligation(document='서약서; 안전보건관리 이행 서약서; 보안각서',stage='검토',
        obligation='확인 필요',deadline='원문 확인',method='원문 확인',timing='시점 미확정',conditions='단계 확인')
    source='서약서\n1\n[별지 제5호 서식]\n안전보건관리 이행 서약서\n1\n[별지 제10호 서식]'
    result=preserve_form_identity(row,[source])
    assert result.document=='서약서 [별지 제5호 서식]; 안전보건관리 이행 서약서 [별지 제10호 서식]; 보안각서'
    assert preserve_form_identity(result,[source])==result
    assert preserve_form_identity(row,[source,'서약서\n1\n[별지 제9호 서식]']).document.startswith('서약서;')


def test_source_named_contract_obligation_cannot_be_completed_by_registration_copy():
    from apps.api.app.copilot.submission_obligations import explicit_stage_obligations, SubmissionObligation
    from apps.api.app.copilot.acceptance import freeze_acceptance, assess_acceptance
    from apps.api.app.copilot.v31_contracts import Claim
    _, b, plan = setup()
    b.sources[1].quote = '계약상대자는 계약체결 시 첨부된 [별지 제9호 서식] 보안 이행 서약서를 제출하여야 한다.'
    b.facts[1].text = b.sources[1].quote
    plan.goal = '제출 서류와 준비 체크리스트를 만들어줘'
    anchors=explicit_stage_obligations(b,plan.goal)
    assert anchors == [{'stage':'계약체결','document':'보안 이행 서약서','fact_ids':['document']}]
    assert explicit_stage_obligations(b,'소재지를 알려줘') == []
    criteria=tuple(c for c in freeze_acceptance(plan,b) if c.submission_document)
    row=SubmissionObligation(document='보안 이행 서약서',stage='입찰참가등록',stage_kind='입찰참가등록',
        obligation='필수',deadline='등록 시',method='제출',timing='시점 미확정',conditions='원문에 따름')
    claim=Claim(claim_id='c',text='등록 시 서약서 제출',fact_ids=['document'],source_ids=['document'],
        validation='SUPPORTED',method='semantic',submission=row)
    result=Verdicts(verdicts=[],criteria=[dict(criterion_id=criteria[0].criterion_id,status='MET',claim_ids=['c'],reason='model says complete')])
    assessed=assess_acceptance(criteria,result,[claim])
    assert assessed['task_coverage']=='PARTIAL'
    assert assessed['criteria'][0]['status']=='MISSING'
    assert 'stage_kind=계약체결' in assessed['criteria'][0]['reason']
    assert '보안 이행 서약서' in assessed['criteria'][0]['reason']
    claim.submission=row.model_copy(update={'stage':'계약체결','stage_kind':'계약체결'})
    assert assess_acceptance(criteria,result,[claim])['task_coverage']=='COMPLETE'


def test_source_permission_survives_a_model_that_omits_it_and_verifier_that_accepts_it():
    from apps.api.app.copilot.evidence_payload import evidence_payload
    from apps.api.app.copilot.answer_validation import mechanical
    from apps.api.app.copilot.v31_contracts import CandidateClaim
    _, bundle, _ = setup()
    bundle.sources[1].quote = '참석자는 제안사(협력사 직원 가능)의 임직원이어야 하며 재직증명서를 제출한다.'
    class Gateway:
        fact_citations = True
        def call(self, stage, prompt, body, schema):
            if stage == 'generate':
                return schema.model_validate({'claims': [dict(claim_id='attendee', text='ignored', fact_ids=['F2'],
                    speech_act='ASSERTION', submission=dict(document='재직증명서', stage='발표', obligation='필수',
                    deadline='발표 시', method='현장 제출', timing='시점 미확정',
                    conditions='참석자는 제안사의 임직원이어야 합니다. 신분증도 지참합니다.'))]})
            self.verified = body['claims'][0]
            return Verdicts(verdicts=[dict(claim_id='attendee', status='SUPPORTED', reason='matches')])
    gateway = Gateway()
    draft = generated_draft(gateway, 'generate', '', {'tasks': [{'kind': 'READ_DOCUMENT'}],
                            'evidence': evidence_payload(bundle)}, bundle)
    claim = draft.claims[0]
    assert '제안사(협력사 직원 가능)의' in claim.text
    assert '신분증도 지참' in claim.text
    verified, _ = verify(draft, bundle, gateway)
    assert '협력사 직원 가능' in gateway.verified['text']
    assert verified[0].validation == 'SUPPORTED'
    narrowed = CandidateClaim(**claim.model_dump())
    narrowed.submission.conditions = '참석자는 제안사 임직원이어야 합니다.'
    assert mechanical(narrowed, bundle) == 'SOURCE_QUALIFIER_OMITTED'


def test_parenthetical_preservation_is_bounded_to_same_subject_and_is_idempotent():
    from apps.api.app.copilot.submission_obligations import SubmissionObligation, preserve_parenthetical_qualifiers
    row = SubmissionObligation(document='허가증',stage='등록',obligation='필수',deadline='미기재',method='미기재',
        timing='시점 미확정',conditions='등록업체만 참여할 수 있습니다.')
    quote = '등록업체(소기업 제외)만 참여 가능. 운반업체(대행 허용)는 별도 확인.'
    changed = preserve_parenthetical_qualifiers(row,[quote])
    assert changed.conditions == '등록업체(소기업 제외)만 참여할 수 있습니다.'
    assert preserve_parenthetical_qualifiers(changed,[quote]) == changed
    assert preserve_parenthetical_qualifiers(row,['다른업체(대행 허용)는 별도 확인.']) == row
    # Conflicting source qualifications need semantic/source review, not an arbitrary pick.
    assert preserve_parenthetical_qualifiers(row,['등록업체(대기업 가능)', '등록업체(대기업 제외)']) == row

