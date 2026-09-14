"""실제 후보/요청/실행 모듈을 읽고 모델 I/O만 대역으로 교체하는 독립 단위 테스트."""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
import types
import unittest
from dataclasses import replace
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "app/ai/qualification/extraction"
_PACKAGE = "_qualification_review_execution_tests"
if _PACKAGE not in sys.modules:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(_PATH)]
    sys.modules[_PACKAGE] = package
runtime = importlib.import_module(f"{_PACKAGE}.review_execution")
planning = importlib.import_module(f"{_PACKAGE}.review_plan")
bridge = importlib.import_module(f"{_PACKAGE}.review_extraction")


def block(index=0, text="가. 업종코드 1450으로 등록한 업체", doc="D1", **kwargs):
    return {"document_id": doc, "block_index": index, "text": text, "page": 2, **kwargs}


def plan(blocks=None, **kwargs):
    inventory = planning.build_review_inventory([block()] if blocks is None else blocks, notice_version_id="V1")
    return planning.plan_review_requests(inventory, **kwargs)


def slot(key, quote="1450", name="업종_raw", type_="업종요건", basis="SELF_CONTAINED"):
    return {"type": type_, "basis": basis,
            "fields": [{"name": name, "source_candidate_id": key, "quote": quote}]}


def decision(key, *, status="REQUIREMENT", reason=None, slots=None):
    if status != "REQUIREMENT":
        return {"candidate_id": key, "status": status, "reason": reason, "slots": []}
    return {"candidate_id": key, "status": status, "reason": reason,
            "slots": [slot(key)] if slots is None else slots}


class FakeExtractor:
    model = "test-only-model"
    temperature = 0
    seed = 1
    api_key = "DO_NOT_LOG_PRIVATE_KEY"
    last_system_fingerprint = None
    unsupported_parameters = ()

    def __init__(self, handler=None):
        self.calls = []
        self.handler = handler or (lambda payload, n: {"decisions": [decision(key) for key in payload["target_candidate_ids"]]})

    def __call__(self, system, body, schema):
        self.calls.append((system, body, copy.deepcopy(schema)))
        self.last_system_fingerprint = f"fp-{len(self.calls)}"
        return self.handler(json.loads(body), len(self.calls))


def run(p=None, handler=None, **options):
    p = plan() if p is None else p
    extractor = FakeExtractor(handler)
    result = runtime.execute_review_plan(p, structured_extract=extractor, options=runtime.ReviewOptions(**options))
    return result, extractor


class ResponseTests(unittest.TestCase):
    def test_schema_objects_are_closed_and_all_fields_required(self):
        schema = runtime.review_response_schema()
        def walk(node):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                self.assertFalse(node["additionalProperties"])
                self.assertEqual(set(node["properties"]), set(node["required"]))
            for value in node.values():
                if isinstance(value, dict):
                    walk(value)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)
        walk(schema)
        encoded = json.dumps(schema, ensure_ascii=False)
        self.assertNotIn('"raw"', encoded)
        self.assertNotIn('"start_offset"', encoded)
        self.assertNotIn('"value"', encoded)

    def test_complete_response_has_server_resolved_span(self):
        result, _ = run()
        field = result.decisions[0].slots[0].fields[0]
        source = result.plan.inventory.units[0].candidate
        self.assertEqual(result.coverage.coverage_status, "COMPLETE")
        self.assertEqual(source.text[field.start_offset:field.end_offset], field.quote)
        self.assertEqual(field.quote, "1450")

    def test_subclause_offsets_are_in_original_block(self):
        p = plan([block(text="3. 참가자격\n가. 업종코드 1450 등록 업체")])
        target = p.inventory.units[1].candidate.candidate_id
        def handler(payload, n):
            return {"decisions": [decision(k) if k == target else decision(k, status="NOT_REQUIREMENT", reason="표제")
                                  for k in payload["target_candidate_ids"]]}
        result, _ = run(p, handler)
        field = result.decisions[1].slots[0].fields[0]
        self.assertEqual("3. 참가자격\n가. 업종코드 1450 등록 업체"[field.start_offset:field.end_offset], "1450")

    def test_reordered_decisions_are_canonicalized(self):
        p = plan([block(0), block(1, doc="D2")])
        normal, _ = run(p)
        reversed_, _ = run(p, lambda payload, n: {"decisions": list(reversed([decision(k) for k in payload["target_candidate_ids"]]))})
        self.assertEqual(normal.decisions, reversed_.decisions)
        self.assertEqual(normal.coverage, reversed_.coverage)

    def test_missing_only_retry_keeps_ids_context_and_successes(self):
        p = plan([block(text="3. 참가자격\n가. 업종코드 1450 등록\n나. 업종코드 1450 신고\n※ 다음 안내")])
        target = p.inventory.units[2].candidate.candidate_id
        def handler(payload, n):
            ids = payload["target_candidate_ids"]
            if n == 1:
                ids = [k for k in ids if k != target]
            return {"decisions": [decision(k, status="NOT_REQUIREMENT", reason="프로토콜 테스트") for k in ids]}
        result, model = run(p, handler)
        self.assertEqual(result.coverage.coverage_status, "COMPLETE")
        self.assertEqual(len(model.calls), 2)
        second = json.loads(model.calls[1][1])
        self.assertEqual(second["target_candidate_ids"], [target])
        self.assertIn(p.inventory.units[0].candidate.candidate_id, [s["candidate_id"] for s in second["sources"]])
        self.assertEqual(result.plan.inventory, p.inventory)

    def test_empty_response_stays_incomplete_after_retry_limit(self):
        result, model = run(handler=lambda p, n: {"decisions": []}, max_retries=2)
        self.assertEqual(len(model.calls), 3)
        self.assertEqual(result.coverage.coverage_status, "INCOMPLETE")
        self.assertEqual(result.coverage.processed_count, 0)

    def test_zero_retries_does_not_repeat(self):
        _, model = run(handler=lambda p, n: {"decisions": []}, max_retries=0)
        self.assertEqual(len(model.calls), 1)

    def test_unresolved_does_not_retry_same_context(self):
        for status in ("UNRESOLVED", "NEEDS_CONTEXT"):
            with self.subTest(status=status):
                result, model = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], status=status, reason="추가 해석 필요")]})
                self.assertEqual(len(model.calls), 1)
                self.assertEqual(result.coverage.coverage_status, "INCOMPLETE")

    def test_explicit_not_requirement_is_recorded(self):
        result, _ = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], status="NOT_REQUIREMENT", reason="문의처")]})
        self.assertEqual(result.coverage.coverage_status, "COMPLETE")
        self.assertEqual(len(result.coverage.non_requirement_candidate_ids), 1)

    def test_reason_is_required_for_non_requirement(self):
        result, model = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], status="NOT_REQUIREMENT")]})
        self.assertEqual(result.coverage.coverage_status, "INVALID")
        self.assertEqual(len(model.calls), 1)

    def test_duplicate_id_not_last_write_wins(self):
        def handler(p, n):
            k = p["target_candidate_ids"][0]
            return {"decisions": [decision(k), decision(k, status="NOT_REQUIREMENT", reason="충돌")]}
        result, model = run(handler=handler)
        self.assertEqual(result.decisions, ())
        self.assertEqual(result.coverage.coverage_status, "INVALID")
        self.assertEqual(len(model.calls), 1)

    def test_duplicate_id_does_not_discard_independent_valid_sibling(self):
        p = plan([block(0), block(1, text="나. 업종코드 1450 등록")])
        def handler(payload, n):
            a, b = payload["target_candidate_ids"]
            return {"decisions": [decision(a), decision(a), decision(b)]}
        result, _ = run(p, handler)
        self.assertEqual(len(result.decisions), 1)
        self.assertEqual(result.decisions[0].candidate_id, p.inventory.units[1].candidate.candidate_id)
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_foreign_id_quarantines_whole_batch(self):
        result, model = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0]), decision("foreign")]})
        self.assertEqual(result.decisions, ())
        self.assertEqual(result.coverage.coverage_status, "INVALID")
        self.assertEqual(len(model.calls), 1)

    def test_context_only_id_is_not_processed(self):
        p = plan([block(text="3. 참가자격\n가. 업종코드 1450 등록")])
        p = planning.plan_review_requests(p.inventory, target_candidate_ids=[p.inventory.units[1].candidate.candidate_id])
        parent = p.inventory.units[0].candidate.candidate_id
        result, _ = run(p, lambda payload, n: {"decisions": [decision(parent)]})
        self.assertEqual(result.coverage.coverage_status, "INVALID")
        self.assertEqual(result.coverage.processed_count, 0)

    def test_invalid_root_is_not_silent_empty(self):
        for root in (None, [], {}, {"requirements": []}, {"decisions": "bad"}, {"decisions": [], "extra": 1}):
            with self.subTest(root=root):
                result, model = run(handler=lambda p, n: root)
                self.assertEqual(result.coverage.coverage_status, "INVALID")
                self.assertEqual(len(model.calls), 1)

    def test_unidentified_row_does_not_trigger_guessing(self):
        for row in (None, {}, {"candidate_id": []}):
            with self.subTest(row=row):
                result, _ = run(handler=lambda p, n: {"decisions": [row]})
                self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_wrong_or_missing_keys_are_invalid(self):
        for mutate in (lambda row: row.update(raw="새 문장"), lambda row: row.pop("reason"),
                       lambda row: row.update(status="SATISFIED"), lambda row: row.update(slots=[])):
            def handler(p, n):
                row = decision(p["target_candidate_ids"][0]); mutate(row)
                return {"decisions": [row]}
            result, _ = run(handler=handler)
            self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_duplicate_slot_is_not_silently_folded(self):
        result, _ = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], slots=[slot(p["target_candidate_ids"][0])]*2)]})
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_duplicate_field_is_rejected(self):
        def handler(p, n):
            s = slot(p["target_candidate_ids"][0]); s["fields"] *= 2
            return {"decisions": [decision(p["target_candidate_ids"][0], slots=[s])]}
        result, _ = run(handler=handler)
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_slot_type_and_basis_are_checked(self):
        for change in ({"type": "NEW_TYPE"}, {"basis": []}, {"fields": None}):
            def handler(p, n):
                s = slot(p["target_candidate_ids"][0]); s.update(change)
                return {"decisions": [decision(p["target_candidate_ids"][0], slots=[s])]}
            result, _ = run(handler=handler)
            self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_non_requirement_with_slot_is_invalid(self):
        def handler(p, n):
            k = p["target_candidate_ids"][0]
            return {"decisions": [{**decision(k), "status": "NOT_REQUIREMENT", "reason": "문의처"}]}
        result, _ = run(handler=handler)
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_unrelated_source_id_is_not_accepted(self):
        result, _ = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], slots=[slot("outside")])]})
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_present_in_batch_but_not_target_context_is_rejected(self):
        p = plan([block(0), block(1, text="나. 안내"), block(2, text="다. 예산 5억원")], neighbor_radius=0)
        target = p.inventory.units[0].candidate.candidate_id
        other = p.inventory.units[2].candidate.candidate_id
        def handler(payload, n):
            return {"decisions": [decision(k, slots=[slot(other, "5억원", "금액_raw")]) if k == target
                                  else decision(k, status="NOT_REQUIREMENT", reason="안내") for k in payload["target_candidate_ids"]]}
        result, _ = run(p, handler)
        self.assertIn(target, result.invalid_candidate_ids)

    def test_wrong_quote_is_rejected_and_not_retried(self):
        for quote in ("145O", "1450; 1227", "", "  "):
            with self.subTest(quote=quote):
                result, model = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], slots=[slot(p["target_candidate_ids"][0], quote)])]})
                self.assertEqual(result.coverage.coverage_status, "INVALID")
                self.assertEqual(len(model.calls), 1)

    def test_ambiguous_quote_does_not_choose_first_occurrence(self):
        result, _ = run(plan([block(text="1450 등록; 설명 1450")]))
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_related_context_quote_is_grounded_but_not_semantically_certified(self):
        p = plan([block(0), block(1, text="※ 1일 평균 800식")])
        target, note = [u.candidate.candidate_id for u in p.inventory.units]
        def handler(payload, n):
            return {"decisions": [decision(target, slots=[slot(note, "800식", "경험분야_raw", basis="CONTEXT_DEPENDENT")]),
                                  decision(note, status="NOT_REQUIREMENT", reason="연결 근거") ]}
        result, _ = run(p, handler)
        self.assertEqual(result.coverage.coverage_status, "COMPLETE")
        self.assertEqual(result.decisions[0].slots[0].basis, "CONTEXT_DEPENDENT")

    def test_no_candidates_no_call(self):
        result, model = run(plan([]))
        self.assertEqual(result.coverage.coverage_status, "EMPTY")
        self.assertEqual(model.calls, [])

    def test_char_blocked_plan_no_call(self):
        result, model = run(plan(max_body_chars=1))
        self.assertEqual(model.calls, [])
        self.assertEqual(result.coverage.coverage_status, "INCOMPLETE")

    def test_call_budget_leaves_unsent_targets_visible(self):
        p = plan([block(0, doc="A"), block(0, doc="B")])
        result, model = run(p, max_calls=1)
        self.assertEqual(len(model.calls), 1)
        self.assertEqual(result.coverage.coverage_status, "INCOMPLETE")
        self.assertEqual(result.events[-1]["outcome"], "CALL_BUDGET_EXCEEDED")

    def test_api_exception_is_not_retried_or_logged_verbatim(self):
        def handler(p, n):
            raise RuntimeError("DO_NOT_LOG_PRIVATE_KEY or private source")
        result, model = run(handler=handler)
        encoded = json.dumps(result.audit())
        self.assertEqual(len(model.calls), 1)
        self.assertIn("CALL_FAILED", encoded)
        self.assertNotIn("DO_NOT_LOG_PRIVATE_KEY", encoded)
        self.assertNotIn("private source", encoded)

    def test_token_budget_blocks_without_cutting_input(self):
        result, model = run(max_input_tokens=1, token_counter=lambda *args: 2)
        self.assertEqual(model.calls, [])
        self.assertEqual(result.events[0]["outcome"], "INPUT_TOKEN_BUDGET_EXCEEDED")

    def test_token_budget_accepts_exact_limit(self):
        result, model = run(max_input_tokens=2, token_counter=lambda *args: 2)
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(result.events[0]["token_budget_checked"])

    def test_token_counter_must_return_valid_integer(self):
        for count in (-1, True, 1.5, None):
            result, model = run(max_input_tokens=10, token_counter=lambda *args: count)
            self.assertEqual(model.calls, [])
            self.assertEqual(result.events[0]["outcome"], "BUDGET_CHECK_FAILED")

    def test_late_response_is_discarded(self):
        now = [0.0]
        def handler(p, n):
            now[0] = 20.0
            return {"decisions": [decision(p["target_candidate_ids"][0])]}
        model = FakeExtractor(handler)
        result = runtime.execute_review_plan(plan(), structured_extract=model,
            options=runtime.ReviewOptions(max_elapsed_seconds=10), clock=lambda: now[0])
        self.assertEqual(result.decisions, ())
        self.assertEqual(result.events[0]["outcome"], "LATE_RESPONSE_DISCARDED")

    def test_oversized_response_rejected(self):
        result, _ = run(max_response_chars=5)
        self.assertEqual(result.coverage.coverage_status, "INVALID")
        self.assertEqual(result.events[0]["code"], "RESPONSE_TOO_LARGE")

    def test_slots_count_is_bounded(self):
        def handler(p, n):
            k = p["target_candidate_ids"][0]
            return {"decisions": [decision(k, slots=[slot(k)] * 2)]}
        result, _ = run(handler=handler, max_slots_per_candidate=1)
        self.assertEqual(result.coverage.coverage_status, "INVALID")

    def test_invalid_options_fail_before_call(self):
        for options in ({"max_retries": -1}, {"max_calls": 0}, {"max_calls": True},
                        {"max_elapsed_seconds": float('nan')}, {"max_elapsed_seconds": float('inf')},
                        {"max_input_tokens": 5}, {"token_counter": lambda *args: 5}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                runtime.ReviewOptions(**options)

    def test_tampered_request_is_rejected_before_call(self):
        p = plan(); request = replace(p.requests[0], body='{}')
        model = FakeExtractor()
        with self.assertRaises(ValueError):
            runtime.execute_review_plan(replace(p, requests=(request,)), structured_extract=model)
        self.assertEqual(model.calls, [])

    def test_prompt_schema_and_request_hashes_match_calls(self):
        result, model = run()
        event = result.events[0]
        system, body, schema = model.calls[0]
        self.assertEqual(event["prompt_sha256"], hashlib.sha256(system.encode()).hexdigest())
        self.assertEqual(event["body_sha256"], hashlib.sha256(body.encode()).hexdigest())
        self.assertEqual(event["schema_sha256"], runtime._sha(runtime._json(schema)))
        self.assertEqual(event["model_after"]["last_system_fingerprint"], "fp-1")

    def test_schema_mutation_by_adapter_does_not_leak_to_retry(self):
        class Mutator(FakeExtractor):
            def __call__(self, system, body, schema):
                self.assert_clean = "corrupt" not in schema
                self.calls.append(schema)
                schema["corrupt"] = True
                return {"decisions": []}
        model = Mutator()
        runtime.execute_review_plan(plan(), structured_extract=model)
        self.assertTrue(model.assert_clean)
        self.assertNotIn("corrupt", runtime.review_response_schema())

    def test_response_is_not_mutated(self):
        p = plan(); response = {"decisions": [decision(p.target_candidate_ids[0])]}
        original = copy.deepcopy(response)
        run(p, lambda payload, n: response)
        self.assertEqual(response, original)

    def test_audit_has_no_source_quote_or_model_reason(self):
        reason = "INTERNAL_SOURCE_EXCERPT_FOR_REASON"
        result, _ = run(handler=lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0], status="UNRESOLVED", reason=reason)]})
        encoded = json.dumps(result.audit(), ensure_ascii=False)
        self.assertNotIn(reason, encoded)
        self.assertNotIn(block()["text"], encoded)
        self.assertNotIn(FakeExtractor.api_key, encoded)


class BridgeTests(unittest.TestCase):
    def test_raw_is_server_source_and_locators_are_preserved(self):
        blocks = [block(text="  가. 업종코드 1450으로 등록한 업체\r\n", source_sha256="a"*64)]
        original = copy.deepcopy(blocks)
        result = bridge.extract_review_slots(blocks, notice_version_id="V1", structured_extract=FakeExtractor())
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["slots"][0]["raw"], blocks[0]["text"])
        self.assertEqual(result["slots"][0]["_source_blocks"][0]["page"], 2)
        self.assertEqual(result["slots"][0]["_source_blocks"][0]["source_sha256"], "a"*64)
        self.assertEqual(blocks, original)

    def test_all_explicit_not_requirement_is_not_automatic_success(self):
        model = FakeExtractor(lambda p, n: {"decisions": [decision(k, status="NOT_REQUIREMENT", reason="표제") for k in p["target_candidate_ids"]]})
        result = bridge.extract_review_slots([block()], notice_version_id="V1", structured_extract=model)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["slots"], [])
        self.assertEqual(result["review_audit"]["coverage"]["coverage_status"], "COMPLETE")

    def test_missing_sibling_makes_partial_while_retaining_valid_slot(self):
        model = FakeExtractor(lambda p, n: {"decisions": [decision(p["target_candidate_ids"][0])] if n == 1 else []})
        result = bridge.extract_review_slots([block(0), block(1, text="나. 업종코드 1450 등록")], notice_version_id="V1", structured_extract=model)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["slots"]), 1)

    def test_context_dependent_candidate_is_held_as_a_whole(self):
        def handler(p, n):
            k = p["target_candidate_ids"][0]
            return {"decisions": [decision(k, slots=[slot(k), slot(k, basis="CONTEXT_DEPENDENT")])]}
        result = bridge.extract_review_slots([block()], notice_version_id="V1", structured_extract=FakeExtractor(handler))
        self.assertEqual(result["slots"], [])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["review_audit"]["adapter_pending"][0]["codes"], ["CONTEXT_APPLICABILITY_PENDING"])

    def test_context_quote_does_not_become_wrong_primary_evidence(self):
        blocks = [block(0), block(1, text="※ 800식")]
        def handler(p, n):
            a, b = p["target_candidate_ids"]
            return {"decisions": [decision(a, slots=[slot(b, "800식", "경험분야_raw")]),
                                  decision(b, status="NOT_REQUIREMENT", reason="각주")]}
        result = bridge.extract_review_slots(blocks, notice_version_id="V1", structured_extract=FakeExtractor(handler))
        self.assertEqual(result["slots"], [])
        self.assertIn("MULTI_SOURCE_REQUIREMENT_PENDING", result["review_audit"]["adapter_pending"][0]["codes"])

    def test_unresolved_annex_is_held(self):
        result = bridge.extract_review_slots([block(text="별표 2 조건 및 업종코드 1450")], notice_version_id="V1", structured_extract=FakeExtractor())
        self.assertEqual(result["slots"], [])
        self.assertIn("UNRESOLVED_DOCUMENT_REFERENCE", result["review_audit"]["adapter_pending"][0]["codes"])

    def test_source_gap_is_not_complete_analysis(self):
        result = bridge.extract_review_slots([block(0), block(2)], notice_version_id="V1", structured_extract=FakeExtractor())
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["review_audit"]["plan"]["source_gaps"])

    def test_empty_inventory_is_failed_and_not_called(self):
        model = FakeExtractor()
        result = bridge.extract_review_slots([], notice_version_id="V1", structured_extract=model)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(model.calls, [])

    def test_budget_unsent_targets_not_in_sent_ids(self):
        result = bridge.extract_review_slots([block()], notice_version_id="V1", structured_extract=FakeExtractor(), options=runtime.ReviewOptions(max_body_chars=1))
        self.assertEqual(result["target_chunk_ids"], [])
        self.assertEqual(result["review_audit"]["plan"]["scheduled_count"], 0)

    def test_no_generated_detail_is_logged_in_span_metadata(self):
        result = bridge.extract_review_slots([block()], notice_version_id="V1", structured_extract=FakeExtractor())
        span = result["review_audit"]["accepted_slot_sources"][0]["field_spans"][0]
        self.assertNotIn("quote", span)
        self.assertGreater(span["end_offset"], span["start_offset"])

    def test_different_response_order_keeps_slot_order_stable(self):
        blocks = [block(0), block(1)]
        one = bridge.extract_review_slots(blocks, notice_version_id="V1", structured_extract=FakeExtractor())
        two = bridge.extract_review_slots(blocks, notice_version_id="V1", structured_extract=FakeExtractor(
            lambda p, n: {"decisions": [decision(k) for k in reversed(p["target_candidate_ids"])]}))
        self.assertEqual(one["slots"], two["slots"])


if __name__ == "__main__":
    unittest.main()
