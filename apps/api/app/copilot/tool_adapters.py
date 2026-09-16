"""Adapt existing domain reads; no alternate judgment engine and no writes."""
import json
import os

from ..document_rag.readiness import digest, full_source_request, inspect_index, read_passages, snapshot_sources
from ..document_rag.service import load_notice_version_for_rag
from ..document_rag.store import create_openai_embeddings
from ..qualification.judgment import QualificationJudgmentError
from . import product_tools
from .actions import get_changed_notice
from .narration import _profile_for_ai, STATUS_CONCLUSION
from .v31_contracts import EvidenceBundle, Fact, Scope, Source, StatusCard


class ProductTools:
    def __init__(self, db, case, *, allow_documents=False, gateway=None):
        self.db, self.case = db, case
        self.allow_documents, self.gateway = allow_documents, gateway
        self.scope = Scope(case_id=case.id, company_id=case.company_id, notice_id=case.notice_id,
                           notice_version_id=case.current_version_id)
        self.bundle = EvidenceBundle(scope=self.scope)
        self.summary = None
        self.checks = None
        self.card = None
        self.trace = []

    def _source(self, kind, quote, *, scope=None, evidence=None, location=None):
        scope = scope or self.scope
        location = location or (evidence.location if evidence else {})
        if hasattr(location, 'model_dump'):
            location = location.model_dump(mode='json', exclude_none=True)
        if evidence and getattr(evidence, 'notice_version_id', str(scope.notice_version_id)) != str(scope.notice_version_id):
            raise ValueError('EVIDENCE_SCOPE_MISMATCH')
        source_id = 's-' + digest([kind, quote, scope.model_dump(mode='json'), str(getattr(evidence, 'document_id', '')), location])[:20]
        source = Source(source_id=source_id, kind=kind, quote=quote, scope=scope,
                        document_id=str(evidence.document_id) if evidence and evidence.document_id else None,
                        location=location,
                        source_sha256=evidence.source_sha256 if evidence else None,
                        extracted_sha256=evidence.extracted_text_sha256 if evidence else None)
        if source_id not in {s.source_id for s in self.bundle.sources}:
            self.bundle.sources.append(source)
        return source_id

    def _fact(self, kind, text, ids, *, target='DOCUMENT', key=None, scope=None, origin=None, entity=None):
        scope = scope or self.scope
        fact_id = 'f-' + digest([kind, text, ids, scope.model_dump(mode='json')])[:20]
        if fact_id not in {f.fact_id for f in self.bundle.facts}:
            self.bundle.facts.append(Fact(fact_id=fact_id, kind=kind, text=text, source_ids=ids,
                                          target_kind=target, requirement_key=key, scope=scope,
                                          origin_tool=origin, entity_ref=entity or key))
        return fact_id

    def _summary(self):
        if self.summary is not None:
            return self.summary
        summary = product_tools.get_qualification_summary(self.db, self.case.id)
        p = summary.provenance
        if p.case_id != self.scope.case_id or p.company_id != self.scope.company_id or p.notice_version_id != self.scope.notice_version_id:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        self.scope = self.scope.model_copy(update={'analysis_run_id': p.analysis_run_id, 'judgment_run_id': p.judgment_run_id})
        self.bundle.scope = self.scope
        self.summary = summary
        self.bundle.server_context = {**self.bundle.server_context, 'overall_status': summary.overall_status,
                                      'judgment_counts': summary.judgment_counts,
                                      'provenance': p.model_dump(mode='json')}
        # The same causal context accompanies document follow-ups as well as
        # judgment reads. RULE_MATCH alone does not mean a license was checked.
        self.bundle.server_context['judgment_basis'] = [self._judgment_basis(j,summary.profile_snapshot) for j in summary.judgments]
        if any(str(j.evaluated_condition.get('source_group',{}).get('review_scope','')).startswith('LOCAL_')
               for j in summary.judgments):
            self.bundle.limitations.append('업종군 결합 관계는 이 로컬 검수 자료의 가정으로만 적용했습니다. 실제 공고의 법적 해석을 확정한 것이 아닙니다.')
        self.bundle.fingerprints['product'] = digest(summary.model_dump(mode='json'))
        return summary

    @staticmethod
    def _judgment_basis(item, snapshot=None):
        from ..qualification.rules.source_contracts import confirmation_fields
        profile=_profile_for_ai(snapshot or {})
        def comparison_values(value):
            # The rule engine uses verified only for evidence_held, never for
            # status. Do not present that flag as a comparison operand.
            if isinstance(value, dict):
                return {k:comparison_values(v) for k,v in value.items() if k != 'verified'}
            if isinstance(value, list):return [comparison_values(v) for v in value]
            return value
        keys={'INDUSTRY':['industries'],'REGION':['region_code','region_name'],
              'COMPANY_SIZE':['company_size'],'STAFF':['staff'],'EXPERIENCE_FIELD':['performances'],
              'PERFORMANCE_AMOUNT':['performances'],'PERFORMANCE_COUNT':['performances'],
              'REGISTRATION_CERTIFICATION':['certifications']}.get(item.type,[])
        contract=item.evaluated_condition.get('source_contract')
        fields=confirmation_fields(contract) if contract else []
        answer_meaning = (' / '.join(label for _,label in fields)
            + (' 조건 전체를 충족한다는 사용자 확인 답변으로 저장한 결과' if item.status=='SATISFIED'
               else ' 조건 전체를 충족하지 않는다는 사용자 확인 답변으로 저장한 결과')) if fields else '사용자 답변에 따른 판정'
        if contract and contract.get('kind')=='WASTE_TRANSPORT' and item.basis_type=='USER_ANSWER':
            answer_meaning += '. 운반업 코드 등록을 인정한 결과가 아니라 별도 등록 예외의 복합 확인 답변이다'
        comparison_semantics = (
            '실적 후보의 날짜 범위를 확인한 뒤 저장 실적명 또는 분야와 요건 비교값을 문자열 대조한다. '
            '운영기간·식수·기관유형을 각각 계산한 판정이 아니다. 그 상세 정보의 누락을 RULE_MISMATCH의 직접 원인으로 추론하지 않는다. '
            '실제 복합 실적 조건을 입증할 추가 자료와 현재 저장 규칙의 비교 결과는 구분해야 한다.'
        ) if item.type == 'EXPERIENCE_FIELD' and item.basis_type == 'PROFILE' else None
        return {'requirement': item.raw, 'status': item.status, 'basis_type': item.basis_type,
                'value_source': item.value_source, 'evidence_status': item.evidence_status,
                'unknown_reason': item.unknown_reason, 'condition': item.evaluated_condition,
                'stored_profile_inputs':{k:comparison_values(profile[k]) for k in keys} if snapshot else {},
                'verification_flags_affect_status':False,
                'comparison_semantics':comparison_semantics,
                'evidence_meaning':'verified/증빙 보유 표시는 근거 기록이며 충족·미달을 정하는 비교값이 아님. 미검증 또는 증빙 없음 자체를 미달 원인으로 설명하지 않는다. 실제 증빙 검증이나 회사의 실제 미보유를 뜻하지 않음',
                'meaning': answer_meaning + '. 실제 증빙 검증이 아님' if item.basis_type == 'USER_ANSWER'
                           else '저장된 회사정보를 규칙과 비교한 판정이며 실제 증빙 검증이 아님' if item.basis_type == 'PROFILE'
                           else '판정 근거가 부족하거나 조건이 불확실하여 자동 비교를 확정하지 못함'}

    def judgment(self):
        summary = self._summary()
        self.card = StatusCard(status=summary.overall_status, text=STATUS_CONCLUSION[summary.overall_status], provenance=summary.provenance)
        counts = summary.judgment_counts
        text = (f'현재 저장 판정: {STATUS_CONCLUSION[summary.overall_status]} '
                f"충족 {counts.get('SATISFIED', 0)}건, 미달 {counts.get('UNSATISFIED', 0)}건, 확인 필요 {counts.get('UNKNOWN', 0)}건. "
                f'분석 상태: {summary.analysis_status}. 저장된 결과이며 현실의 모든 자격을 새로 확인했다는 뜻은 아닙니다.')
        self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text)], origin='READ_JUDGMENT', entity='judgment_summary')
        evidence = product_tools.get_explanation_evidence(self.db, self.case.id, [r.requirement_key for r in summary.judgments])
        if any(e.provenance != summary.provenance for e in evidence):
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        by_key = {e.requirement.requirement_key: e.evidence for e in evidence}
        for item in summary.judgments:
            text = f'저장된 요건 상태: {item.status}. 요건: {item.raw}. 사유 코드: {item.reason_code}.'
            text += '\n판정에 사용된 기준: ' + json.dumps(self._judgment_basis(item,summary.profile_snapshot), ensure_ascii=False)
            ids = [self._source('PRODUCT', text)]
            ids += [self._source('DOCUMENT', e.quote, evidence=e) for e in by_key[item.requirement_key] if e.quote.strip()]
            self._fact('SERVER_RESULT', text, ids, target='REQUIREMENT', key=item.requirement_key, origin='READ_JUDGMENT')
        if summary.analysis_status == 'PARTIAL':
            self.bundle.limitations.append('현재 분석은 부분 완료 상태이며 자동 판정 범위가 완전하지 않습니다.')

    def profile(self):
        summary = self._summary()
        profile = product_tools.get_judgment_profile_snapshot(self.db, self.case.id)
        if profile.provenance != summary.provenance:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        text = '판정 당시 회사정보: ' + json.dumps(_profile_for_ai(profile.profile_snapshot), ensure_ascii=False)
        self._fact('PROFILE_FACT', text, [self._source('PRODUCT', text)], origin='READ_PROFILE', entity='profile_snapshot')

    def required_checks(self, *, answerable_only=False):
        summary = self._summary()
        checks = product_tools.get_required_checks(self.db, self.case.id)
        if checks.provenance != summary.provenance:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        self.checks = checks
        scope = None if answerable_only else summary.analysis_scope
        questions = [q for q in checks.questions if q.askable] if answerable_only else checks.questions
        evidence = product_tools.get_explanation_evidence(self.db, self.case.id, [q.requirement_key for q in questions]) if questions else []
        if any(e.provenance != summary.provenance for e in evidence):
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        by_key = {e.requirement.requirement_key:e.evidence for e in evidence}
        self.bundle.capabilities.update(answerable_count=sum(q.askable for q in questions),
                                        unanswerable_count=sum(not q.askable for q in questions),
                                        manual_review_count=(len(scope.notice_facts) + len(scope.dropped_requirements)) if scope else 0)
        for q in questions:
            text = ('답변 입력 가능: ' if q.askable else '직접 확인 필요·현재 입력 불가: ') + q.question
            ids = [self._source('PRODUCT', text)]
            ids += [self._source('DOCUMENT', e.quote, evidence=e) for e in by_key[q.requirement_key] if e.quote.strip()]
            fid=self._fact('SERVER_RESULT', text, ids, target='REQUIREMENT', key=q.requirement_key, origin='READ_CHECKS')
            self.bundle.server_context.setdefault('check_guidance',{})[fid]={'input_allowed':q.askable,'text':text}
        if answerable_only and not questions:
            text = '현재 저장된 판정에서 추가 답변을 입력할 수 있는 확인 질문은 없습니다. 모든 참가조건이 충족됐다는 뜻은 아닙니다.'
            self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text)], origin='READ_CHECKS', entity='checks_empty')
        if scope:
            for item in scope.notice_facts:
                cited = [e for e in item.evidence if e.quote.strip()]
                ids = list(dict.fromkeys(self._source('DOCUMENT', e.quote, evidence=e) for e in cited))
                if ids:
                    manual = '직접 원문 검토 대상입니다. 이 항목은 저장 판정의 답변 입력 대상이 아니며 회사의 실제 충족 여부를 확정한 결과가 아닙니다.'
                    ids.append(self._source('PRODUCT', manual))
                    fid=self._fact('NOTICE_FACT', manual + '\n' + '\n'.join(e.quote for e in cited), ids, target='MANUAL', origin='READ_CHECKS',
                                   entity='manual-' + digest([item.code, ids])[:20])
                    self.bundle.server_context.setdefault('check_guidance',{})[fid]={'input_allowed':False,
                        'text':'직접 확인할 조건: '
                        + '\n'.join(dict.fromkeys(e.quote for e in cited))
                        + '\n앱의 답변 입력 대상이 아닙니다.'}
            for item in scope.dropped_requirements:
                # Raw dropped requirement alone has no original locator; never invent a citation.
                self.bundle.limitations.append('구조화에서 제외된 항목은 참가자격 화면에서 원문을 확인해 주세요: ' + item.raw)

    def documents(self, question):
        if not self.allow_documents:
            self.bundle.coverage['READ_DOCUMENT'] = 'UNAVAILABLE'
            self.bundle.limitations.append('공고문 근거 답변을 켜면 현재 공개 문서를 함께 확인할 수 있습니다.')
            return
        snapshot = snapshot_sources(load_notice_version_for_rag(self.db, self.case.current_version_id))
        self.bundle.fingerprints['document'] = snapshot.fingerprint
        embeddings = self.gateway or create_openai_embeddings()
        readiness = inspect_index(snapshot, os.getenv('DOCUMENT_RAG_INDEX_ROOT', 'data/document-rag'), embeddings)
        # When no model key exists, lexical current-section reads require no query embedding.
        if not embeddings.available:
            readiness.index = None
        from .acceptance import notice_documents_deadlines_request
        # A list of documents and their deadlines spans notice sections.
        # Lexical top-k can match only generic '공고' and miss inflected words.
        broad = full_source_request(question) or notice_documents_deadlines_request(question)
        from ..document_rag.langchain_pipeline import retrieve_current
        try:
            passages, details = retrieve_current(readiness, question, broad=broad)
        except Exception:
            readiness.index = None
            passages, details = retrieve_current(readiness, question, broad=broad)
            details['query_embedding_failed'] = True
        target = getattr(self, 'selected_target', None)
        from ..document_rag.readiness import pack_current_passages
        if broad:
            passages = pack_current_passages(passages)
            details['model_passages'] = len(passages)
            details['packing'] = 'adjacent_source_text_no_omissions'
        if target and target.origin_tool == 'READ_DOCUMENT' and target.entity_ref:
            # The target stores the original chunk identity. Do not search using
            # generated answer prose to locate an already selected source.
            candidates = pack_current_passages(snapshot.records) if target.entity_ref.startswith('packet-') else snapshot.records
            passages = [r for r in candidates if r.metadata.chunk_id == target.entity_ref]
            details['strategy'] = 'selected_current_chunk'
        self.trace.append({'tool': 'READ_DOCUMENT', 'source_status': snapshot.source_status,
                           'index_status': readiness.index_status, 'generation': readiness.generation,
                           'fingerprint': snapshot.fingerprint, 'verification': snapshot.verification, **details})
        self.bundle.limitations.extend(snapshot.limitations)
        self.bundle.coverage['READ_DOCUMENT'] = 'FOUND' if passages else 'NOT_FOUND'
        if snapshot.source_status != 'AVAILABLE':
            self.bundle.limitations.append('확인 가능한 문서 범위가 제한되어 전체 조건을 확인했다고 볼 수 없습니다.')
            if broad and passages:
                self.bundle.coverage['READ_DOCUMENT'] = 'PARTIAL'
        from types import SimpleNamespace
        for passage in passages:
            m = passage.metadata
            if m.notice_version_id != str(self.scope.notice_version_id):
                raise ValueError('DOCUMENT_SCOPE_MISMATCH')
            evidence = SimpleNamespace(document_id=m.document_id, source_sha256=m.source_sha256,
                                       extracted_text_sha256=m.extracted_text_sha256,
                                       location={'chunk_id': m.chunk_id, 'page': m.page, 'locations': m.source_locations})
            sid = self._source('DOCUMENT', passage.text, evidence=evidence)
            self._fact('NOTICE_FACT', passage.text, [sid], origin='READ_DOCUMENT', entity=m.chunk_id)

    def changes(self):
        result = get_changed_notice(self.db, self.case.id)
        p = result.provenance
        if (p.case_id != self.scope.case_id or p.company_id != self.scope.company_id
                or p.notice_id != self.scope.notice_id or p.current.notice_version_id != self.scope.notice_version_id):
            raise ValueError('CHANGE_SCOPE_MISMATCH')
        self.bundle.fingerprints['changes'] = digest(result.model_dump(mode='json'))
        from .change_impact import read_change_impact, impact_text
        impact = read_change_impact(self.db, result)
        self.bundle.fingerprints['change_impact'] = digest(impact)
        self.bundle.server_context['change_impact'] = impact
        text = impact_text(impact)
        self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text,
            location={'revalidation_id': impact.get('lineage_id'),
                      'source_judgment_id': impact.get('source_judgment_id'),
                      'result_judgment_id': impact.get('result_judgment_id')})],
            target='CHANGE', origin='READ_CHANGES', entity='saved_change_impact')
        from collections import Counter
        from .change_impact import structured_change_kind
        classifications = Counter(structured_change_kind(c) for c in result.changes if c.change_type != 'UNCHANGED')
        text = (f"저장 분석 변경 감지 {sum(classifications.values())}건: 구조화된 판정 값 변경 {classifications['STRUCTURED_VALUE_CHANGED']}건, "
                f"구조화 값 동일 {classifications['STRUCTURED_VALUE_SAME']}건, 요건 추가 {classifications['ADDED']}건, 삭제 {classifications['REMOVED']}건. "
                'MODIFIED 표시는 원문·출처의 차이도 포함하므로 구조화 값 변경과 같지 않습니다. 실제 공고 조항의 변경 여부는 별도 원문 대조로 확인합니다.')
        self._fact('SERVER_RESULT',text,[self._source('PRODUCT',text)],target='CHANGE',origin='READ_CHANGES',entity='structured_change_classification')
        labels={'ADDED':'저장 분석 요건 추가','REMOVED':'저장 분석 요건 삭제',
                'STRUCTURED_VALUE_CHANGED':'구조화된 판정 값 변경','STRUCTURED_VALUE_SAME':'구조화된 판정 값 동일'}
        for change in result.changes:
            for label, version, requirement in [('이전', result.provenance.baseline, change.baseline), ('현재', result.provenance.current, change.current)]:
                if requirement is None:
                    continue
                scope = self.scope.model_copy(update={'notice_version_id': version.notice_version_id,
                                                      'analysis_run_id': version.analysis_run_id, 'judgment_run_id': version.judgment_run_id})
                text = f'저장 분석 요건 대조 — {label} 버전 {version.version_number}: {requirement.raw} ({labels[structured_change_kind(change)]}). 구조화 값이 동일하면 원문 표기·출처 정보 차이를 실제 판정 값 변경으로 설명하지 않습니다. 원문 변경 여부와 회사 판정 변화는 별도 확인해야 합니다.'
                self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text, scope=scope)], target='CHANGE', scope=scope,
                           origin='READ_CHANGES', entity=str(version.notice_version_id) + ':' + requirement.raw)
        if self.allow_documents:
            from .source_changes import compare_sources
            before = load_notice_version_for_rag(self.db, self.case.baseline_version_id)
            after = load_notice_version_for_rag(self.db, self.case.current_version_id)
            if before.notice_id != self.scope.notice_id or after.notice_id != self.scope.notice_id:
                raise ValueError('CHANGE_DOCUMENT_SCOPE_MISMATCH')
            fingerprint, observations, limitations = compare_sources(before, after)
            self.bundle.fingerprints['change_sources'] = fingerprint
            self.bundle.limitations.extend(limitations)
            for index, text in enumerate(observations):
                self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text)], target='CHANGE',
                           origin='READ_CHANGES', entity='literal-source-comparison-' + str(index))
            if limitations:
                self.bundle.coverage['READ_CHANGES'] = 'PARTIAL'

    def execute(self, task):
        if task.kind == 'READ_JUDGMENT': self.judgment()
        elif task.kind == 'READ_PROFILE': self.profile()
        elif task.kind == 'READ_CHECKS':
            from .acceptance import answerable_checks_request
            self.required_checks(answerable_only=answerable_checks_request(task.question))
        elif task.kind == 'READ_DOCUMENT': self.documents(task.question)
        elif task.kind == 'READ_CHANGES': self.changes()
        self.bundle.coverage.setdefault(task.kind, 'FOUND')

    def assert_fresh(self):
        self.db.refresh(self.case)
        if self.case.current_version_id != self.scope.notice_version_id or self.case.company_id != self.scope.company_id:
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        if self.summary is not None:
            current = product_tools.get_qualification_summary(self.db, self.case.id)
            if digest(current.model_dump(mode='json')) != self.bundle.fingerprints['product']:
                raise ValueError('PRODUCT_SCOPE_CHANGED')
        if 'document' in self.bundle.fingerprints:
            current = snapshot_sources(load_notice_version_for_rag(self.db, self.case.current_version_id))
            if current.fingerprint != self.bundle.fingerprints['document']:
                raise ValueError('DOCUMENT_SCOPE_CHANGED')
        if 'changes' in self.bundle.fingerprints:
            current = get_changed_notice(self.db, self.case.id)
            if digest(current.model_dump(mode='json')) != self.bundle.fingerprints['changes']:
                raise ValueError('CHANGE_SCOPE_CHANGED')
            if 'change_impact' in self.bundle.fingerprints:
                from .change_impact import read_change_impact
                if digest(read_change_impact(self.db, current)) != self.bundle.fingerprints['change_impact']:
                    raise ValueError('CHANGE_IMPACT_CHANGED')
        if 'change_sources' in self.bundle.fingerprints:
            from .source_changes import compare_sources
            fingerprint, _, _ = compare_sources(
                load_notice_version_for_rag(self.db, self.case.baseline_version_id),
                load_notice_version_for_rag(self.db, self.case.current_version_id))
            if fingerprint != self.bundle.fingerprints['change_sources']:
                raise ValueError('CHANGE_DOCUMENT_SCOPE_CHANGED')
