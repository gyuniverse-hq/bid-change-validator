"""실제 provider 계약과 orchestration 분기의 단위 연결 검증.

모델/DB를 호출하지 않는다. provider는 client_factory로 I/O만 교체한다.
analysis_pipeline은 실제 파일을 로드하되 기존 청커/정규화/canonical/result builder를
테스트 대역으로 바꾼다. 이 테스트는 전체 API/판정 회귀나 실모델 E2E가 아니다.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

from test_review_execution import FakeExtractor, block, bridge, decision, plan, run, runtime

_APP = Path(__file__).resolve().parents[1] / "app"
_PROVIDER = _APP / "ai/providers/openai.py"
_SPEC = importlib.util.spec_from_file_location("_review_real_provider", _PROVIDER)
assert _SPEC and _SPEC.loader
provider = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(provider)


class ProviderTests(unittest.TestCase):
    def test_real_provider_serializes_review_schema_and_decodes_decisions(self):
        calls = []
        def create(**kwargs):
            calls.append(copy.deepcopy(kwargs))
            payload = json.loads(kwargs["messages"][1]["content"])
            content = json.dumps({"decisions": [decision(key) for key in payload["target_candidate_ids"]]})
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content, refusal=None))])
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        extractor = provider.OpenAIStructuredExtractor(api_key="test-not-a-secret", model="test-only-model", client_factory=lambda _: client)
        result = runtime.execute_review_plan(plan(), structured_extract=extractor)
        self.assertEqual(result.coverage.coverage_status, "COMPLETE")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0]["response_format"]["json_schema"]["strict"])
        self.assertEqual(calls[0]["response_format"]["json_schema"]["schema"], runtime.review_response_schema()["schema"])

    def test_provider_refusal_does_not_become_valid_empty_analysis(self):
        def create(**kwargs):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{}', refusal="refused"))])
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        extractor = provider.OpenAIStructuredExtractor(api_key="test-key", model="test-only-model", client_factory=lambda _: client)
        result = runtime.execute_review_plan(plan(), structured_extract=extractor)
        self.assertEqual(result.coverage.coverage_status, "INCOMPLETE")
        self.assertEqual(result.calls, 1)
        self.assertEqual(result.events[0]["outcome"], "CALL_FAILED")

    def test_non_json_provider_output_is_not_retried(self):
        def create(**kwargs):
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"decisions":', refusal=None))])
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        extractor = provider.OpenAIStructuredExtractor(api_key="test-key", model="test-only-model", client_factory=lambda _: client)
        result = runtime.execute_review_plan(plan(), structured_extract=extractor)
        self.assertEqual(result.calls, 1)
        self.assertEqual(result.events[0]["outcome"], "CALL_FAILED")

    def test_unknown_id_cannot_copy_original_text_into_audit(self):
        text = block()["text"]
        result, _ = run(handler=lambda p, n: {"decisions": [decision(text)]})
        encoded = json.dumps(result.audit(), ensure_ascii=False)
        self.assertNotIn(text, encoded)
        self.assertTrue(result.coverage.unknown_candidate_ids[0].startswith("UNKNOWN-"))


class FakeObject(types.SimpleNamespace):
    def model_copy(self, *, update):
        return type(self)(**{**vars(self), **update})


def _load_isolated_pipeline():
    root = "_review_pipeline_wiring_tests"
    for suffix, path in (("", _APP), (".ai", _APP / "ai"),
                         (".ai.qualification", _APP / "ai/qualification"),
                         (".ai.qualification.extraction", _APP / "ai/qualification/extraction"),
                         (".ai.qualification.canonical", _APP / "ai/qualification/canonical")):
        name = root + suffix
        package = types.ModuleType(name); package.__path__ = [str(path)]
        sys.modules[name] = package
    def module(suffix, **members):
        obj = types.ModuleType(root + suffix)
        obj.__dict__.update(members)
        sys.modules[obj.__name__] = obj
    def canonical(slots, **kwargs):
        return {"requirements": slots, "evidence": [], "diagnostics": []}
    def build(**kwargs):
        c = kwargs["canonicalized"]
        status = "SUCCEEDED" if kwargs["extraction_status"] == "ok" else ("PARTIAL" if c["requirements"] else "FAILED")
        return FakeObject(status=status, requirements=c["requirements"], evidence=c["evidence"],
                          diagnostics=list(c["diagnostics"]))
    module(".ai.qualification.extraction.analysis_result", AnalysisDiagnostic=FakeObject,
           RequirementAnalysisResult=FakeObject, build_requirement_analysis_result=build)
    module(".ai.qualification.extraction.backend_blocks", canonical_source_blocks=lambda **kw: kw["blocks"])
    module(".ai.qualification.extraction.chunking", chunk_source_blocks=lambda blocks, **kw: blocks)
    module(".ai.qualification.canonical.canonicalize", canonicalize_validated_slots=canonical)
    module(".ai.normalization", normalize_value=lambda raw: {"raw": raw})
    module(".ai.qualification.extraction.requirement_extraction", StructuredExtractor=object,
           extract_legacy_slots=lambda *args, **kw: {"slots": [], "status": "ok"})
    name = root + ".ai.qualification.extraction.analysis_pipeline"
    spec = importlib.util.spec_from_file_location(name, _APP / "ai/qualification/extraction/analysis_pipeline.py")
    assert spec and spec.loader
    value = importlib.util.module_from_spec(spec); sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


class PipelineWiringTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = _load_isolated_pipeline()
        self.input = self.pipeline.QualificationAnalysisInput(notice_id="N1", notice_version_id="V1", documents=[{
            "document_id": "D1", "file_sha256": "f"*64,
            "extracted_text_sha256": "e"*64, "extracted_blocks": [block()] }])

    def test_default_remains_legacy_and_keeps_legacy_result(self):
        old = Mock(return_value={"slots": [{"raw": "legacy"}], "status": "ok"})
        self.pipeline.extract_legacy_slots = old
        model = FakeExtractor()
        result = self.pipeline.analyze_qualification_documents(self.input, structured_extract=model)
        old.assert_called_once()
        self.assertEqual(result.requirements, [{"raw": "legacy"}])
        self.assertEqual(model.calls, [])
        self.assertEqual(result.diagnostics, [])

    def test_explicit_review_calls_new_runner_and_old_canonical_boundary(self):
        old = Mock(side_effect=AssertionError("legacy must not run"))
        canonical = Mock(side_effect=lambda slots, **kw: {"requirements": slots, "evidence": [], "diagnostics": []})
        self.pipeline.extract_legacy_slots = old
        self.pipeline.canonicalize_validated_slots = canonical
        result = self.pipeline.analyze_qualification_documents(self.input, structured_extract=FakeExtractor(), extraction_strategy="review_v1")
        self.assertEqual(result.requirements[0]["raw"], block()["text"])
        canonical.assert_called_once()
        old.assert_not_called()
        self.assertEqual(result.diagnostics[-1].code, "REVIEW_EXECUTION_AUDIT")

    def test_backend_document_identity_overrides_block_supplied_identity(self):
        self.input.documents[0].extracted_blocks[0].update(document_id="OTHER", source_sha256="bad", extracted_text_sha256="bad")
        result = self.pipeline.analyze_qualification_documents(self.input, structured_extract=FakeExtractor(), extraction_strategy="review_v1")
        source = result.requirements[0]["_source_blocks"][0]
        self.assertEqual(source["document_id"], "D1")
        self.assertEqual(source["source_sha256"], "f"*64)
        self.assertEqual(source["extracted_text_sha256"], "e"*64)

    def test_unmapped_requirement_is_not_turned_into_notice_fact_success(self):
        def canonical(slots, **kw):
            return {"requirements": [], "evidence": ["source"], "diagnostics": [
                FakeObject(code="UNMAPPED_REQUIREMENT", kind="NOTICE_FACT", severity="INFO", message="old") ]}
        self.pipeline.canonicalize_validated_slots = canonical
        result = self.pipeline.analyze_qualification_documents(self.input, structured_extract=FakeExtractor(), extraction_strategy="review_v1")
        self.assertEqual(result.status, "PARTIAL")
        self.assertEqual(result.diagnostics[0].kind, "PIPELINE")
        self.assertEqual(result.diagnostics[0].severity, "WARNING")

    def test_unknown_strategy_fails_before_call(self):
        model = FakeExtractor()
        with self.assertRaises(ValueError):
            self.pipeline.analyze_qualification_documents(self.input, structured_extract=model, extraction_strategy="typo")
        self.assertEqual(model.calls, [])

    def test_review_options_cannot_silently_be_ignored_in_legacy(self):
        with self.assertRaises(ValueError):
            self.pipeline.analyze_qualification_documents(self.input, structured_extract=FakeExtractor(), review_options=self.pipeline.ReviewOptions())

    def test_missing_backend_locator_is_not_invented(self):
        del self.input.documents[0].extracted_blocks[0]["block_index"]
        model = FakeExtractor()
        with self.assertRaises(ValueError):
            self.pipeline.analyze_qualification_documents(self.input, structured_extract=model, extraction_strategy="review_v1")
        self.assertEqual(model.calls, [])

    def test_no_model_calls_when_input_is_empty(self):
        self.input.documents = []
        model = FakeExtractor()
        result = self.pipeline.analyze_qualification_documents(self.input, structured_extract=model, extraction_strategy="review_v1")
        self.assertEqual(result.status, "FAILED")
        self.assertEqual(model.calls, [])
        self.assertEqual(result.diagnostics[-1].details["coverage"]["coverage_status"], "EMPTY")


if __name__ == "__main__":
    unittest.main()
