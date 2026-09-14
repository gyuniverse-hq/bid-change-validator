"""원문 후보/처리 누락 모듈 단위 테스트. DB와 LLM 없이 실행한다.

source loader는 app.ai의 다른 SDK 초기화와 이 표준 라이브러리 모듈의 테스트를
분리하기 위한 것이다. 운영 함수 자체를 로드하며 모듈 구현은 모킹하지 않는다.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "app/ai/qualification/extraction/review_coverage.py"
_SPEC = importlib.util.spec_from_file_location("_review_coverage_under_test", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
build_review_candidates = _MODULE.build_review_candidates
audit_review_coverage = _MODULE.audit_review_coverage


def block(index=0, *, document_id="D1", text="영업신고(업종코드 : 1450)를 한 업체", **kwargs):
    return {"document_id": document_id, "block_index": index, "text": text, **kwargs}


def build(blocks=None, *, version="V1"):
    return build_review_candidates([block()] if blocks is None else blocks, notice_version_id=version)


def response(candidate, status="REQUIREMENT", reason=None):
    return {"candidate_id": candidate.candidate_id, "status": status, "reason": reason}


class CandidateTests(unittest.TestCase):
    def test_exact_text_and_offsets_are_preserved(self):
        text = "  각 단체급식소※(1일 평균 800식 이상)\n㈜ 확인  "
        item = build([block(text=text)])[0]
        self.assertEqual(item.text, text)
        self.assertEqual(text[item.start_offset:item.end_offset], text)
        self.assertEqual(item.block_index, 0)

    def test_no_keyword_filter_removes_a_block(self):
        self.assertEqual(len(build([block(text="가. 위 요건을 모두 충족하여야 한다.")])), 1)

    def test_empty_block_is_not_a_candidate(self):
        self.assertEqual(build([block(text=" \n\t")]), [])

    def test_id_and_order_do_not_depend_on_input_order(self):
        blocks = [block(2), block(1), block(document_id="D2")]
        self.assertEqual(build(blocks), build(reversed(blocks)))

    def test_changing_source_changes_candidate_id(self):
        self.assertNotEqual(build()[0].candidate_id, build([block(text="업종코드 1227")])[0].candidate_id)

    def test_changing_notice_version_changes_candidate_id(self):
        self.assertNotEqual(build()[0].candidate_id, build(version="V2")[0].candidate_id)

    def test_changing_document_changes_candidate_id(self):
        self.assertNotEqual(build()[0].candidate_id, build([block(document_id="D2")])[0].candidate_id)

    def test_changing_context_invalidates_same_document_candidates(self):
        first = build([block(0), block(1, text="예외 A")])
        second = build([block(0), block(1, text="예외 B")])
        self.assertNotEqual(first[0].candidate_id, second[0].candidate_id)

    def test_changing_other_document_does_not_change_id(self):
        first = build([block(), block(document_id="D2", text="A")])
        second = build([block(), block(document_id="D2", text="B")])
        self.assertEqual(first[0].candidate_id, second[0].candidate_id)

    def test_changing_locator_invalidates_id(self):
        self.assertNotEqual(build([block(page=1)])[0].candidate_id,
                            build([block(page=2)])[0].candidate_id)

    def test_ambiguous_source_locations_are_rejected(self):
        for invalid in (None, True, -1, "0"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                build([block(invalid)])
        with self.assertRaises(ValueError):
            build([block(), block()])

    def test_conflicting_source_hashes_are_rejected(self):
        for field in ("source_sha256", "extracted_text_sha256"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                build([block(0, **{field: "a" * 64}), block(1, **{field: "b" * 64})])

    def test_sources_are_not_mutated_and_candidates_are_frozen(self):
        blocks = [block()]
        original = copy.deepcopy(blocks)
        candidate = build(blocks)[0]
        self.assertEqual(blocks, original)
        with self.assertRaises(FrozenInstanceError):
            candidate.text = "changed"

    def test_bad_input_is_rejected_instead_of_inventing_identity(self):
        for blocks in ([None], [block(document_id="")], [block(text=None)]):
            with self.subTest(blocks=blocks), self.assertRaises(ValueError):
                build(blocks)
        with self.assertRaises(ValueError):
            build(version="")


class CoverageTests(unittest.TestCase):
    def setUp(self):
        self.candidates = build([block(0), block(1, text="본점 소재지가 광주인 업체")])

    def test_empty_model_output_is_incomplete(self):
        report = audit_review_coverage(self.candidates, [])
        self.assertEqual(report.coverage_status, "INCOMPLETE")
        self.assertEqual(len(report.missing_candidate_ids), 2)
        self.assertEqual(report.processed_count, 0)

    def test_partial_output_identifies_exact_missing_id(self):
        report = audit_review_coverage(self.candidates, [response(self.candidates[0])])
        self.assertEqual(report.coverage_status, "INCOMPLETE")
        self.assertEqual(report.missing_candidate_ids, (self.candidates[1].candidate_id,))

    def test_complete_responses_are_order_independent(self):
        responses = [response(item) for item in self.candidates]
        first = audit_review_coverage(self.candidates, responses)
        self.assertEqual(first.coverage_status, "COMPLETE")
        self.assertEqual(first, audit_review_coverage(reversed(self.candidates), reversed(responses)))

    def test_no_candidates_is_not_vacuous_success(self):
        self.assertEqual(audit_review_coverage([], []).coverage_status, "EMPTY")

    def test_explicit_exclusion_requires_reason(self):
        item = self.candidates[0]
        invalid = audit_review_coverage([item], [response(item, "NOT_REQUIREMENT")])
        valid = audit_review_coverage([item], [response(item, "NOT_REQUIREMENT", "문의처 안내")])
        self.assertEqual(invalid.coverage_status, "INVALID")
        self.assertEqual(valid.coverage_status, "COMPLETE")
        self.assertEqual(valid.requirement_candidate_ids, ())
        self.assertEqual(valid.non_requirement_candidate_ids, (item.candidate_id,))

    def test_unresolved_and_needs_context_are_not_complete(self):
        responses = [response(self.candidates[0], "UNRESOLVED", "조건 관계 불명확"),
                     response(self.candidates[1], "NEEDS_CONTEXT", "연결된 별표 필요")]
        report = audit_review_coverage(self.candidates, responses)
        self.assertEqual(report.coverage_status, "INCOMPLETE")
        self.assertEqual(report.processed_count, 2)
        self.assertEqual(report.unresolved_candidate_ids, (self.candidates[0].candidate_id,))
        self.assertEqual(report.needs_context_candidate_ids, (self.candidates[1].candidate_id,))

    def test_duplicate_is_invalid_even_when_statuses_agree(self):
        item = self.candidates[0]
        report = audit_review_coverage([item], [response(item), response(item)])
        self.assertEqual(report.coverage_status, "INVALID")
        self.assertEqual(report.duplicate_candidate_ids, (item.candidate_id,))
        self.assertEqual(report.processed_count, 0)

    def test_conflicting_duplicate_is_not_last_write_wins(self):
        item = self.candidates[0]
        responses = [response(item), response(item, "NOT_REQUIREMENT", "분류 충돌")]
        first = audit_review_coverage([item], responses)
        self.assertEqual(first, audit_review_coverage([item], reversed(responses)))
        self.assertEqual(first.requirement_candidate_ids, ())
        self.assertEqual(first.non_requirement_candidate_ids, ())

    def test_unknown_id_is_invalid(self):
        responses = [response(item) for item in self.candidates]
        responses.append({"candidate_id": "invented-id", "status": "REQUIREMENT"})
        report = audit_review_coverage(self.candidates, responses)
        self.assertEqual(report.coverage_status, "INVALID")
        self.assertEqual(report.unknown_candidate_ids, ("invented-id",))

    def test_old_snapshot_response_is_rejected(self):
        old = build([block(text="원문 A")])
        new = build([block(text="원문 B")])
        report = audit_review_coverage(new, [response(old[0])])
        self.assertEqual(report.coverage_status, "INVALID")
        self.assertEqual(report.missing_candidate_ids, (new[0].candidate_id,))

    def test_malformed_responses_are_reported_without_crashing(self):
        for bad in (None, [], {}, {"candidate_id": []}, {"candidate_id": " "},
                    {"candidate_id": self.candidates[0].candidate_id, "status": []},
                    {"candidate_id": self.candidates[0].candidate_id, "status": "SATISFIED"}):
            with self.subTest(bad=bad):
                report = audit_review_coverage(self.candidates, [bad])
                self.assertEqual(report.coverage_status, "INVALID")
                self.assertEqual(report.invalid_response_indexes, (0,))

    def test_invalid_candidate_inventory_is_rejected(self):
        item = self.candidates[0]
        with self.assertRaises(ValueError):
            audit_review_coverage([item, item], [])
        with self.assertRaises(ValueError):
            audit_review_coverage([item, replace(self.candidates[1], notice_version_id="V2")], [])

    def test_report_is_json_serializable_without_source_text(self):
        report = audit_review_coverage(self.candidates, [])
        encoded = json.dumps(report.to_dict(), ensure_ascii=False)
        self.assertNotIn(self.candidates[0].text, encoded)
        self.assertIn("candidate_set_sha256", encoded)


if __name__ == "__main__":
    unittest.main()
