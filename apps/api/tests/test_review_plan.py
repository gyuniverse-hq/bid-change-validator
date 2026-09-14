"""실제 후보/요청 계획 모듈을 DB·SDK·모델 없이 검증한다.

상위 app.ai 패키지의 SDK 초기화만 피한다. 아래 임시 패키지 경로에서 로드하는
review_plan/review_coverage는 저장소의 실제 파일이며 테스트용 대체 구현이 아니다.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import random
import sys
import types
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path

_PACKAGE = "_qualification_review_plan_tests"
_PATH = Path(__file__).resolve().parents[1] / "app/ai/qualification/extraction"
if _PACKAGE not in sys.modules:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(_PATH)]
    sys.modules[_PACKAGE] = package
plan_module = importlib.import_module(f"{_PACKAGE}.review_plan")
coverage_module = importlib.import_module(f"{_PACKAGE}.review_coverage")
build_review_inventory = plan_module.build_review_inventory
plan_review_requests = plan_module.plan_review_requests
audit_review_coverage = coverage_module.audit_review_coverage


def block(index=0, text="가. 업종코드 1450을 등록한 업체", *, document_id="D1", **fields):
    return {"document_id": document_id, "block_index": index, "text": text, **fields}


def inventory(blocks=None, version="V1"):
    return build_review_inventory([block()] if blocks is None else blocks, notice_version_id=version)


def targets(plan):
    return [key for request in plan.requests for key in request.target_candidate_ids]


def unit_with(inv, prefix):
    return next(unit for unit in inv.units if unit.candidate.text.lstrip().startswith(prefix))


def request_for(inv, unit, **kwargs):
    return plan_review_requests(inv, target_candidate_ids=[unit.candidate.candidate_id], **kwargs)


class InventoryTests(unittest.TestCase):
    def test_subclauses_notes_and_whitespace_roundtrip_exactly(self):
        text = " \r\n3. 참가자격\r\n가. ㈜ 업체※(800식)\r\n   계속되는 문장 🧪\r\n※ 예외\r\n나. 등록 조건  "
        inv = inventory([block(text=text)])
        self.assertEqual(len(inv.units), 4)
        self.assertEqual("".join(unit.candidate.text for unit in inv.units), text)
        for unit in inv.units:
            c = unit.candidate
            self.assertEqual(text[c.start_offset:c.end_offset], c.text)
            self.assertEqual(c.block_text_sha256, hashlib.sha256(text.encode()).hexdigest())
        self.assertEqual(inv.units[2].kind, "NOTE")

    def test_keywordless_blocks_are_not_removed(self):
        inv = inventory([block(text="별다른 키워드가 없는 본문"), block(1, "가. 위 조건과 같다.")])
        self.assertEqual(len(inv.units), 2)

    def test_no_marker_keeps_one_exact_unit(self):
        text = "최근 3년\n1.3억원 이상\n기간 36개월\n"
        inv = inventory([block(text=text)])
        self.assertEqual([unit.candidate.text for unit in inv.units], [text])

    def test_single_letter_followed_by_word_is_not_a_heading(self):
        text = "가.등록이 문장 안에서 사용됨\n1.3억원"
        self.assertEqual(inventory([block(text=text)]).units[0].kind, "UNMARKED")

    def test_parent_hierarchy_includes_number_hangul_and_parentheses(self):
        inv = inventory([block(text="3. 참가자격\n가. 업종\n1) 조건\n가) 세부\n(1) 예외\n나. 지역")])
        units = inv.units
        self.assertEqual(units[4].ancestor_ids, tuple(u.candidate.candidate_id for u in units[:4]))
        self.assertEqual(units[5].ancestor_ids, (units[0].candidate.candidate_id,))

    def test_dotted_sections_stay_under_their_numeric_parent(self):
        inv = inventory([block(text="3. 참가자격\n3.1 업종\n가. 코드\n3.2 지역\n나. 소재")])
        units = inv.units
        self.assertEqual(units[2].ancestor_ids, tuple(u.candidate.candidate_id for u in units[:2]))
        self.assertEqual(units[4].ancestor_ids,
                         (units[0].candidate.candidate_id, units[3].candidate.candidate_id))

    def test_chapter_and_article_have_distinct_levels(self):
        inv = inventory([block(text="제1장 안내\n제2조 자격\n1. 기본\n가. 등록")])
        self.assertEqual(len(inv.units[-1].ancestor_ids), 3)

    def test_parent_context_continues_across_source_blocks(self):
        inv = inventory([block(0, "3. 참가자격\n가. 조건"), block(1, "같은 조항의 다음 문장")])
        self.assertEqual(inv.units[-1].ancestor_ids,
                         tuple(u.candidate.candidate_id for u in inv.units[:2]))

    def test_parent_context_does_not_cross_documents(self):
        inv = inventory([block(text="3. 자격"), block(text="가. 다른 문서", document_id="D2")])
        self.assertEqual(inv.units[1].ancestor_ids, ())

    def test_noncontiguous_source_resets_hierarchy_and_records_gap(self):
        inv = inventory([block(0, "3. 자격"), block(1000000000, "가. 중간 원문 없음")])
        self.assertEqual(inv.units[1].ancestor_ids, ())
        self.assertEqual(inv.source_gaps, (("D1", 0, 1000000000),))

    def test_supplied_blank_block_is_not_a_source_gap(self):
        inv = inventory([block(0, "3. 자격"), block(1, " \n"), block(2, "가. 등록")])
        self.assertEqual(inv.source_gaps, ())
        self.assertEqual(inv.units[1].ancestor_ids, (inv.units[0].candidate.candidate_id,))
        self.assertEqual(inv.empty_block_count, 1)
        self.assertEqual(inv.source_block_count, 3)

    def test_empty_inventory_is_not_a_success(self):
        inv = inventory([])
        self.assertEqual(plan_review_requests(inv).status, "EMPTY")
        self.assertEqual(audit_review_coverage(inv.candidates, []).coverage_status, "EMPTY")

    def test_empty_source_and_missing_source_have_different_manifests(self):
        first = inventory([])
        second = inventory([block(text=" \n")])
        self.assertNotEqual(first.input_blocks_sha256, second.input_blocks_sha256)
        self.assertNotEqual(first.inventory_sha256, second.inventory_sha256)

    def test_input_order_does_not_change_units_or_fingerprint(self):
        blocks = [block(2), block(0, "3. 자격"), block(1), block(document_id="D2")]
        self.assertEqual(inventory(blocks), inventory(reversed(blocks)))

    def test_same_text_at_different_positions_has_distinct_ids(self):
        inv = inventory([block(0), block(1)])
        self.assertNotEqual(inv.units[0].candidate.candidate_id, inv.units[1].candidate.candidate_id)

    def test_notice_version_changes_ids(self):
        self.assertNotEqual(inventory().units[0].candidate.candidate_id,
                            inventory(version="V2").units[0].candidate.candidate_id)

    def test_changed_parent_invalidates_child_id(self):
        first = inventory([block(0, "3. 모두 충족"), block(1)])
        second = inventory([block(0, "3. 하나만 충족"), block(1)])
        self.assertNotEqual(first.units[1].candidate.candidate_id, second.units[1].candidate.candidate_id)

    def test_new_document_does_not_renumber_old_document_candidates(self):
        first = inventory([block(document_id="D2")])
        second = inventory([block(document_id="D1"), block(document_id="D2")])
        self.assertEqual(first.units[0].candidate.candidate_id, second.units[1].candidate.candidate_id)

    def test_locator_and_source_hashes_are_preserved(self):
        inv = inventory([block(page=4, location="4쪽 표 2", source_sha256="a"*64,
                               extracted_text_sha256="b"*64)])
        request = plan_review_requests(inv).requests[0]
        record = json.loads(request.body)["sources"][0]
        self.assertEqual(record["location"]["page"], 4)
        self.assertEqual(record["location"]["location"], "4쪽 표 2")
        self.assertEqual(record["source_sha256"], "a"*64)
        self.assertEqual(record["extracted_text_sha256"], "b"*64)

    def test_reference_hints_are_not_resolved_by_guessing(self):
        inv = inventory([block(text="가. 별표 2 및 붙임3 참조")])
        self.assertEqual(inv.units[0].reference_hints, ("별표 2", "붙임3"))
        manifest = plan_review_requests(inv).manifest()
        self.assertEqual(manifest["reference_review_candidate_ids"], [inv.units[0].candidate.candidate_id])

    def test_input_is_not_mutated(self):
        blocks = [block(text="3. 자격\n가. 조건\n※ 예외", page=1)]
        before = copy.deepcopy(blocks)
        plan_review_requests(inventory(blocks))
        self.assertEqual(before, blocks)

    def test_bad_locator_fails_without_inventing_an_id(self):
        for invalid in ([block(None)], [block(), block()], [block(text=None)]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                inventory(invalid)


class RequestPlanTests(unittest.TestCase):
    def test_all_candidates_are_targets_exactly_once(self):
        inv = inventory([block(i, f"{i+1}. 조건 {'문장'*200}") for i in range(25)])
        plan = plan_review_requests(inv, max_targets_per_request=4)
        self.assertEqual(Counter(targets(plan)), Counter(c.candidate_id for c in inv.candidates))
        self.assertTrue(all(len(r.target_candidate_ids) <= 4 for r in plan.requests))
        self.assertEqual(plan.status, "READY")

    def test_more_than_32000_characters_are_batched_not_truncated(self):
        blocks = [block(i, f"{i+1}. {'모든 원문이 남아야 한다 '*180}") for i in range(20)]
        self.assertGreater(sum(len(row["text"]) for row in blocks), 32000)
        inv = inventory(blocks)
        plan = plan_review_requests(inv, max_body_chars=10000)
        self.assertEqual(plan.status, "READY")
        by_id = {c.candidate_id: c for c in inv.candidates}
        self.assertEqual(len(targets(plan)), len(inv.units))
        for request in plan.requests:
            self.assertLessEqual(request.body_chars, 10000)
            records = {row["candidate_id"]: row for row in json.loads(request.body)["sources"]}
            for key in request.target_candidate_ids:
                self.assertEqual(records[key]["text"], by_id[key].text)

    def test_requests_never_mix_documents(self):
        inv = inventory([block(0), block(1), block(document_id="D2")])
        plan = plan_review_requests(inv)
        self.assertEqual(len(plan.requests), 2)
        for request in plan.requests:
            docs = {row["document_id"] for row in json.loads(request.body)["sources"]}
            self.assertEqual(len(docs), 1)

    def test_parent_and_note_are_included_for_a_single_child_target(self):
        inv = inventory([block(text="3. 모두 충족\n가. 1450 등록\n나. 지역\n※ 두 조건에 대한 예외")])
        target = unit_with(inv, "가.")
        plan = request_for(inv, target, neighbor_radius=0)
        data = json.loads(plan.requests[0].body)
        texts = [row["text"] for row in data["sources"]]
        self.assertTrue(any(text.startswith("3.") for text in texts))
        self.assertTrue(any(text.startswith("※") for text in texts))
        self.assertEqual(plan.requests[0].target_candidate_ids, (target.candidate.candidate_id,))
        relations = {link["relation"] for link in data["context_links"][target.candidate.candidate_id]}
        self.assertIn("STRUCTURAL_ANCESTOR", relations)
        self.assertIn("PROXIMITY_NOTE", relations)

    def test_ancestor_section_note_is_available_to_nested_section(self):
        inv = inventory([block(text="3. 자격\n※ 상위 절의 예외\n3.1 업종\n가. 등록")])
        plan = request_for(inv, unit_with(inv, "가."), neighbor_radius=0)
        self.assertTrue(any(row["text"].startswith("※")
                            for row in json.loads(plan.requests[0].body)["sources"]))

    def test_notes_from_other_sections_are_not_attached(self):
        inv = inventory([block(text="3. 자격\n가. 업종\n4. 계약\n※ 다른 절의 주의")])
        plan = request_for(inv, unit_with(inv, "가."), neighbor_radius=0)
        self.assertFalse(any(row["text"].startswith("※")
                             for row in json.loads(plan.requests[0].body)["sources"]))

    def test_neighbor_is_context_not_an_implicit_target(self):
        inv = inventory([block(text="3. 자격\n가. 코드\n나. 소재")])
        target = unit_with(inv, "가.")
        plan = request_for(inv, target)
        self.assertGreater(len(plan.requests[0].source_candidate_ids), 1)
        self.assertEqual(plan.manifest()["scheduled_count"], 1)
        # 문맥으로 포함된 나.에 응답하지 않았다는 사실을 전체 처리 감사는 여전히 잡는다.
        report = audit_review_coverage(inv.candidates,
            [{"candidate_id": target.candidate.candidate_id, "status": "REQUIREMENT"}])
        self.assertEqual(len(report.missing_candidate_ids), len(inv.units)-1)

    def test_missing_only_retry_keeps_identity_and_context(self):
        inv = inventory([block(text="3. 자격\n가. 코드\n나. 소재\n※ 예외")])
        target = unit_with(inv, "나.")
        others = [{"candidate_id": c.candidate_id, "status": "REQUIREMENT"}
                  for c in inv.candidates if c.candidate_id != target.candidate.candidate_id]
        audit = audit_review_coverage(inv.candidates, others)
        retry = plan_review_requests(inv, target_candidate_ids=audit.missing_candidate_ids)
        self.assertEqual(targets(retry), [target.candidate.candidate_id])
        self.assertIn(unit_with(inv, "3.").candidate.candidate_id, retry.requests[0].source_candidate_ids)
        self.assertIn(unit_with(inv, "※").candidate.candidate_id, retry.requests[0].source_candidate_ids)

    def test_oversized_target_is_recorded_not_cut(self):
        inv = inventory([block(text="매우 긴 원문" * 10000)])
        plan = plan_review_requests(inv, max_body_chars=2000)
        self.assertEqual(plan.status, "BLOCKED")
        self.assertEqual(plan.requests, ())
        self.assertEqual(plan.blocked[0].candidate_id, inv.candidates[0].candidate_id)
        self.assertGreater(plan.blocked[0].required_body_chars, 2000)
        self.assertEqual(inv.candidates[0].text, "매우 긴 원문" * 10000)

    def test_oversized_parent_does_not_get_silently_dropped(self):
        inv = inventory([block(text="3. " + "상위조건 "*5000 + "\n가. 등록")])
        plan = request_for(inv, unit_with(inv, "가."), max_body_chars=3000, neighbor_radius=0)
        self.assertEqual(plan.status, "BLOCKED")

    def test_oversized_note_does_not_get_silently_dropped(self):
        inv = inventory([block(text="3. 자격\n가. 등록\n※ " + "예외조건 "*5000)])
        plan = request_for(inv, unit_with(inv, "가."), max_body_chars=3000, neighbor_radius=0)
        self.assertEqual(plan.status, "BLOCKED")

    def test_independent_document_can_be_planned_when_another_is_blocked(self):
        inv = inventory([block(text="긴 원문"*5000), block(document_id="D2")])
        plan = plan_review_requests(inv, max_body_chars=3000)
        self.assertEqual(plan.status, "PARTIAL")
        self.assertEqual(len(plan.blocked), 1)
        self.assertEqual(len(targets(plan)), 1)
        self.assertEqual(set(targets(plan)) | {item.candidate_id for item in plan.blocked},
                         {c.candidate_id for c in inv.candidates})

    def test_budget_boundary_uses_actual_serialized_body(self):
        inv = inventory([block(text='가. "따옴표"\\경로\t와 줄바꿈\n추가')])
        size = plan_review_requests(inv).requests[0].body_chars
        self.assertEqual(plan_review_requests(inv, max_body_chars=size).status, "READY")
        self.assertEqual(plan_review_requests(inv, max_body_chars=size-1).status, "BLOCKED")

    def test_body_hash_matches_the_actual_transmission_string(self):
        plan = plan_review_requests(inventory())
        request = plan.requests[0]
        self.assertEqual(hashlib.sha256(request.body.encode()).hexdigest(), request.body_sha256)
        self.assertEqual(request.request_id, "REQ-" + request.body_sha256)
        self.assertEqual(plan.manifest()["requests"][0]["body_chars"], len(request.body))

    def test_manifest_has_no_source_text_and_is_deterministic(self):
        inv = inventory([block(text="가. 민감한원문표식 ABC987")])
        first = plan_review_requests(inv).manifest()
        self.assertEqual(first, plan_review_requests(inv).manifest())
        self.assertNotIn("민감한원문표식", json.dumps(first, ensure_ascii=False))
        fingerprint = first.pop("plan_sha256")
        self.assertEqual(fingerprint, hashlib.sha256(plan_module._json(first).encode()).hexdigest())

    def test_subset_order_does_not_change_plan(self):
        inv = inventory([block(0), block(1)])
        keys = [c.candidate_id for c in inv.candidates]
        self.assertEqual(plan_review_requests(inv, target_candidate_ids=keys),
                         plan_review_requests(inv, target_candidate_ids=reversed(keys)))

    def test_empty_retry_scope_does_not_schedule_the_whole_inventory(self):
        plan = plan_review_requests(inventory(), target_candidate_ids=[])
        self.assertEqual(plan.status, "EMPTY")
        self.assertEqual(plan.requests, ())
        self.assertEqual(plan.manifest()["inventory_candidate_count"], 1)

    def test_invalid_budgets_are_rejected(self):
        for name in ("max_body_chars", "max_targets_per_request", "neighbor_radius"):
            for value in (True, -1, "10", 0.5):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    plan_review_requests(inventory(), **{name: value})
        for name in ("max_body_chars", "max_targets_per_request"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                plan_review_requests(inventory(), **{name: 0})

    def test_duplicate_unknown_and_stale_target_ids_are_rejected(self):
        inv = inventory()
        key = inv.candidates[0].candidate_id
        stale = inventory(version="V2").candidates[0].candidate_id
        for keys in ([key, key], ["invented"], [None], [stale]):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                plan_review_requests(inv, target_candidate_ids=keys)

    def test_invalid_inventory_links_and_versions_are_rejected(self):
        inv = inventory()
        unit = inv.units[0]
        for bad in (replace(unit, ancestor_ids=("missing",)),
                    replace(unit, candidate=replace(unit.candidate, notice_version_id="V2")),
                    replace(unit, candidate=replace(unit.candidate, end_offset=1))):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                plan_review_requests(replace(inv, units=(bad,)))

    def test_partition_and_source_roundtrip_across_varied_budgets(self):
        rng = random.Random(20260915)
        blocks = [block(i, f"{i+1}. " + ("조건🧪 " * rng.randrange(1, 150))) for i in range(12)]
        inv = inventory(blocks)
        expected = Counter(c.candidate_id for c in inv.candidates)
        for budget in (1, 2000, 4000, 8000, 16000):
            with self.subTest(budget=budget):
                plan = plan_review_requests(inv, max_body_chars=budget, max_targets_per_request=3)
                assigned = targets(plan) + [item.candidate_id for item in plan.blocked]
                self.assertEqual(Counter(assigned), expected)
                self.assertTrue(all(request.body_chars <= budget for request in plan.requests))
                for request in plan.requests:
                    for row in json.loads(request.body)["sources"]:
                        source = blocks[row["block_index"]]["text"]
                        self.assertEqual(source[row["start_offset"]:row["end_offset"]], row["text"])


if __name__ == "__main__":
    unittest.main()
