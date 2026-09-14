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
        self.bundle.server_context = {'overall_status': summary.overall_status,
                                      'judgment_counts': summary.judgment_counts,
                                      'provenance': p.model_dump(mode='json')}
        self.bundle.fingerprints['product'] = digest(summary.model_dump(mode='json'))
        return summary

    def judgment(self):
        summary = self._summary()
        self.card = StatusCard(status=summary.overall_status, text=STATUS_CONCLUSION[summary.overall_status], provenance=summary.provenance)
        evidence = product_tools.get_explanation_evidence(self.db, self.case.id, [r.requirement_key for r in summary.judgments])
        if any(e.provenance != summary.provenance for e in evidence):
            raise ValueError('PRODUCT_SCOPE_CHANGED')
        by_key = {e.requirement.requirement_key: e.evidence for e in evidence}
        for item in summary.judgments:
            text = f'저장된 요건 상태: {item.status}. 요건: {item.raw}. 사유 코드: {item.reason_code}.'
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
            self._fact('SERVER_RESULT', text, ids, target='REQUIREMENT', key=q.requirement_key, origin='READ_CHECKS')
        if answerable_only and not questions:
            text = '현재 저장된 판정에서 추가 답변을 입력할 수 있는 확인 질문은 없습니다. 모든 참가조건이 충족됐다는 뜻은 아닙니다.'
            self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text)], origin='READ_CHECKS', entity='checks_empty')
        if scope:
            for item in scope.notice_facts:
                cited = [e for e in item.evidence if e.quote.strip()]
                ids = list(dict.fromkeys(self._source('DOCUMENT', e.quote, evidence=e) for e in cited))
                if ids:
                    self._fact('NOTICE_FACT', '\n'.join(e.quote for e in cited), ids, target='MANUAL', origin='READ_CHECKS',
                               entity='manual-' + digest([item.code, ids])[:20])
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
        try:
            passages, details = read_passages(readiness, question, broad=broad)
        except Exception:
            readiness.index = None
            passages, details = read_passages(readiness, question, broad=broad)
            details['query_embedding_failed'] = True
        target = getattr(self, 'selected_target', None)
        if target and target.origin_tool == 'READ_DOCUMENT' and target.entity_ref:
            # The target stores the original chunk identity. Do not search using
            # generated answer prose to locate an already selected source.
            passages = [r for r in snapshot.records if r.metadata.chunk_id == target.entity_ref]
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
        for change in result.changes:
            for label, version, requirement in [('이전', result.provenance.baseline, change.baseline), ('현재', result.provenance.current, change.current)]:
                if requirement is None:
                    continue
                scope = self.scope.model_copy(update={'notice_version_id': version.notice_version_id,
                                                      'analysis_run_id': version.analysis_run_id, 'judgment_run_id': version.judgment_run_id})
                text = f'{label} 버전 {version.version_number}: {requirement.raw} ({change.change_type})'
                self._fact('SERVER_RESULT', text, [self._source('PRODUCT', text, scope=scope)], target='CHANGE', scope=scope,
                           origin='READ_CHANGES', entity=str(version.notice_version_id) + ':' + requirement.raw)

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
