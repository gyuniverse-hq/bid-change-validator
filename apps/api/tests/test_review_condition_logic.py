"""조건 의미·논리·중복·동일 실적 집계를 검증한다. 자연어 모델 정확도 테스트는 아니다."""
from __future__ import annotations

from dataclasses import replace
import importlib
from itertools import product
import json
from pathlib import Path
import sys
import types

import pytest

_PACKAGE = "_qualification_reliability_step4"
if _PACKAGE not in sys.modules:
    package = types.ModuleType(_PACKAGE)
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "app/ai/qualification/extraction")]
    sys.modules[_PACKAGE] = package
C = importlib.import_module(f"{_PACKAGE}.review_conditions")
T, F, U = "SATISFIED", "UNSATISFIED", "UNKNOWN"


def atom(key, value=None, *, evidence=None, subject="BIDDER", **kw):
    data = {"type": "INDUSTRY", "operator": "MATCH", "value": value if value is not None else key,
            "unit": None, "period_months": None, "scope": {}, **kw}
    return C.AtomicCondition.from_requirement(key, data, subject=subject, evidence_ids=evidence or ("E-" + key,))


def leaf(key, atom_id=None):
    return C.ConditionNode(key, "ATOM", atom_id=atom_id or key)


def group(key, operator, *children):
    return C.ConditionNode(key, operator, tuple(children), evidence_ids=("E-relation-" + key,))


def pair(operator="ALL_OF"):
    return C.ConditionGraph("root", (leaf("A"), leaf("B"), group("root", operator, "A", "B")),
                            (atom("A"), atom("B")))


def nested():
    return C.ConditionGraph("root", (leaf("A"), leaf("CERT"), leaf("B"),
        group("branch1", "ALL_OF", "A", "CERT"), group("root", "ANY_OF", "branch1", "B")),
        (atom("A", "1257"), atom("CERT", "ISO 9001", type="REGISTRATION_CERTIFICATION"), atom("B", "1227")))


@pytest.mark.parametrize(("a", "b", "want"), [(T,T,T), (T,F,F), (T,U,U), (F,T,F), (F,F,F), (F,U,F), (U,T,U), (U,F,F), (U,U,U)])
def test_all_of_truth_table(a, b, want):
    assert C.evaluate_condition_graph(pair(), {"A": a, "B": b}) == want


@pytest.mark.parametrize(("a", "b", "want"), [(T,T,T), (T,F,T), (T,U,T), (F,T,T), (F,F,F), (F,U,U), (U,T,T), (U,F,U), (U,U,U)])
def test_any_of_truth_table(a, b, want):
    assert C.evaluate_condition_graph(pair("ANY_OF"), {"A": a, "B": b}) == want


@pytest.mark.parametrize(("value", "want"), [(T,F), (F,T), (U,U)])
def test_negation_is_not_missing_as_negative(value, want):
    graph = C.ConditionGraph("not", (leaf("A"), group("not", "NOT", "A")), (atom("A"),))
    assert C.evaluate_condition_graph(graph, {"A": value}) == want


@pytest.mark.parametrize(("required", "exempt", "want"), [(F,T,T), (F,F,F), (F,U,U), (U,F,U), (U,T,T), (T,U,T)])
def test_explicit_exemption_semantics(required, exempt, want):
    assert C.evaluate_condition_graph(pair("EXEMPT_IF"), {"A": required, "B": exempt}) == want


def test_nested_or_does_not_drop_certificate():
    graph = nested()
    assert C.evaluate_condition_graph(graph, {"A": T, "CERT": F, "B": F}) == F
    assert C.evaluate_condition_graph(graph, {"A": T, "CERT": T, "B": F}) == T
    assert C.evaluate_condition_graph(graph, {"A": F, "CERT": F, "B": T}) == T
    assert C.evaluate_condition_graph(graph, {"A": T, "B": F}) == U


def test_missing_atom_is_unknown():
    assert C.evaluate_condition_graph(pair(), {}) == U


def test_orphan_atom_or_node_is_not_silently_lost():
    graph = pair()
    with pytest.raises(C.ConditionError, match="ORPHANED_CONDITION"):
        C.validate_graph(replace(graph, atoms=(*graph.atoms, atom("C"))))
    with pytest.raises(C.ConditionError, match="ORPHANED_CONDITION"):
        C.validate_graph(replace(graph, nodes=(*graph.nodes, leaf("other", "A"))))


@pytest.mark.parametrize("field", ["operator", "value", "unit", "period_months", "scope", "subject", "requirement_role"])
def test_every_semantic_axis_affects_identity(field):
    first = atom("one", "1450")
    kw = {"operator": ">=", "value": "1227", "unit": "KRW", "period_months": 36,
          "scope": {"role": "MIN_OPERATION_DURATION"}, "subject": "CONSORTIUM_LEADER",
          "requirement_role": "preferred"}
    args = {field: kw[field]}
    other = atom("other", **args) if field == "value" else atom("other", "1450", **args)
    assert first.semantic_sha256 != other.semantic_sha256


def test_tax_and_aggregation_scope_change_identity():
    a = atom("a", 200000000, type="PERFORMANCE_AMOUNT", operator=">=", scope={"aggregation":"MAX", "tax_basis":"INCLUDED"})
    b = atom("b", 200000000, type="PERFORMANCE_AMOUNT", operator=">=", scope={"aggregation":"SUM", "tax_basis":"INCLUDED"})
    c = atom("c", 200000000, type="PERFORMANCE_AMOUNT", operator=">=", scope={"aggregation":"MAX", "tax_basis":"EXCLUDED"})
    assert len({a.semantic_sha256, b.semantic_sha256, c.semantic_sha256}) == 3


def test_id_source_and_raw_are_not_semantic_content():
    a = atom("a", "1450", raw="첫 원문", evidence=("E1",))
    b = atom("b", "1450", raw="다른 표현", evidence=("E2",))
    assert a.semantic_sha256 == b.semantic_sha256


def test_scope_key_order_does_not_change_identity():
    a = atom("a", "1450", scope={"b": 2, "a": 1})
    b = atom("b", "1450", scope={"a": 1, "b": 2})
    assert a.semantic_sha256 == b.semantic_sha256


def test_graph_identity_ignores_order_and_labels_but_not_logic():
    original = pair()
    reordered = replace(original, nodes=tuple(reversed(original.nodes)), atoms=tuple(reversed(original.atoms)))
    reversed_children = replace(original, nodes=(*original.nodes[:2], group("root", "ALL_OF", "B", "A")))
    renamed = C.ConditionGraph("other", (leaf("x", "A"), leaf("y", "B"), group("other", "ALL_OF", "x", "y")), original.atoms)
    assert len({C.semantic_fingerprint(item) for item in (original, reordered, reversed_children, renamed)}) == 1
    assert C.semantic_fingerprint(original) != C.semantic_fingerprint(pair("ANY_OF"))


def test_exemption_identity_preserves_requirement_exemption_order():
    graph = pair("EXEMPT_IF")
    reversed_graph = replace(graph, nodes=(*graph.nodes[:2], group("root", "EXEMPT_IF", "B", "A")))
    assert C.semantic_fingerprint(graph) != C.semantic_fingerprint(reversed_graph)


def shared_a_graph():
    return C.ConditionGraph("root", (leaf("a1", "A1"), leaf("a2", "A2"), leaf("b", "B"), leaf("c", "C"),
        group("g1", "ANY_OF", "a1", "b"), group("g2", "ANY_OF", "a2", "c"), group("root", "ALL_OF", "g1", "g2")),
        (atom("A1", "1450"), atom("A2", "1450"), atom("B", "1227"), atom("C", "1257")))


def test_dedup_preserves_both_group_edges_and_combines_evidence():
    original = shared_a_graph()
    result = C.deduplicate_atoms(original)
    assert len(original.atoms) == 4 and len(result.atoms) == 3
    assert len(result.nodes) == len(original.nodes)
    nodes = {node.node_id: node for node in result.nodes}
    assert nodes["a1"].atom_id == nodes["a2"].atom_id
    assert nodes["g1"].children == ("a1", "b") and nodes["g2"].children == ("a2", "c")
    shared = next(a for a in result.atoms if a.atom_id == nodes["a1"].atom_id)
    assert shared.evidence_ids == ("E-A1", "E-A2")
    assert C.semantic_fingerprint(original) == C.semantic_fingerprint(result)
    assert C.deduplicate_atoms(result) == result


@pytest.mark.parametrize(("a", "b", "c"), list(product((T,F,U), repeat=3)))
def test_dedup_preserves_all_27_three_valued_outcomes(a, b, c):
    original = shared_a_graph()
    result = C.deduplicate_atoms(original)
    before = {"A1": a, "A2": a, "B": b, "C": c}
    after = {"ATOM-" + item.semantic_sha256: before[item.atom_id] for item in original.atoms}
    assert C.evaluate_condition_graph(original, before) == C.evaluate_condition_graph(result, after)


def test_different_thresholds_are_not_deduplicated():
    items = (atom("A", 5, type="STAFF", operator=">="), atom("B", 5, type="STAFF", operator=">"))
    graph = replace(pair(), atoms=items)
    assert len(C.deduplicate_atoms(graph).atoms) == 2


def test_certificate_is_not_folded_by_similar_industry_name():
    items = (atom("A", "단체급식업", type="INDUSTRY"), atom("B", "단체급식업", type="REGISTRATION_CERTIFICATION"))
    assert len(C.deduplicate_atoms(replace(pair(), atoms=items)).atoms) == 2


def test_matching_scope_is_immutable_from_input_changes():
    scope = {"constraints": [1, 2]}
    a = atom("A", "1450", scope=scope)
    digest = a.semantic_sha256
    scope["constraints"].append(3)
    assert a.semantic_sha256 == digest


@pytest.mark.parametrize("kwargs", [
    {"operator": None}, {"value": None, "operator": "="}, {"value": True},
    {"value": float("nan")}, {"value": float("inf")}, {"period_months": -1},
    {"period_months": True}, {"period_months": float("nan")}, {"scope": []},
    {"unit": []}, {"required": False}, {"condition_complexity": "composite"},
    {"unrecognized_semantic_field": "do not discard"},
])
def test_invalid_atomic_data_is_rejected(kwargs):
    data = {"type": "STAFF", "operator": ">=", "value": 5, **kwargs}
    with pytest.raises(C.ConditionError):
        C.AtomicCondition.from_requirement("A", data, subject="BIDDER", evidence_ids=("E1",))


def test_missing_evidence_is_rejected():
    with pytest.raises(C.ConditionError, match="MISSING_ATOM_EVIDENCE"):
        C.AtomicCondition.from_requirement("A", {"type":"INDUSTRY", "operator":"MATCH", "value":"1450"}, subject="BIDDER", evidence_ids=())
    graph = pair()
    with pytest.raises(C.ConditionError, match="UNKNOWN_EVIDENCE"):
        C.validate_graph(graph, available_evidence_ids=("E-A", "E-B"))
    C.validate_graph(graph, available_evidence_ids=("E-A", "E-B", "E-relation-root"))


def test_empty_graph_cannot_be_true():
    with pytest.raises(C.ConditionError):
        C.evaluate_condition_graph(C.ConditionGraph("root", (), ()), {})


@pytest.mark.parametrize("operator", ["UNKNOWN", "XOR", None, []])
def test_unknown_operator_is_rejected(operator):
    graph = pair()
    with pytest.raises(C.ConditionError):
        C.validate_graph(replace(graph, nodes=(*graph.nodes[:2], replace(graph.nodes[-1], operator=operator))))


def test_graph_structure_errors_are_rejected():
    graph = pair()
    malformed = [
        replace(graph, root_id="missing"),
        replace(graph, nodes=(*graph.nodes, graph.nodes[0])),
        replace(graph, atoms=(*graph.atoms, graph.atoms[0])),
        replace(graph, nodes=(*graph.nodes[:2], group("root", "ALL_OF", "A", "missing"))),
        replace(graph, nodes=(*graph.nodes[:2], group("root", "ALL_OF", "A", "A"))),
        replace(graph, nodes=(*graph.nodes[:2], group("root", "ALL_OF", "A"))),
        replace(graph, nodes=(*graph.nodes[:2], replace(graph.nodes[-1], evidence_ids=()))),
        replace(graph, nodes=(*graph.nodes[:2], replace(graph.nodes[-1], atom_id="A"))),
    ]
    for bad in malformed:
        with pytest.raises(C.ConditionError):
            C.validate_graph(bad)


def test_cycle_is_rejected():
    graph = C.ConditionGraph("root", (group("root", "NOT", "loop"), group("loop", "NOT", "root")), ())
    with pytest.raises(C.ConditionError, match="CYCLIC_GRAPH"):
        C.validate_graph(graph)


def test_depth_limit():
    nodes = [leaf("leaf", "A")]
    last = "leaf"
    for i in range(34):
        key = f"not-{i}"
        nodes.append(group(key, "NOT", last))
        last = key
    with pytest.raises(C.ConditionError, match="GRAPH_TOO_DEEP"):
        C.validate_graph(C.ConditionGraph(last, tuple(nodes), (atom("A"),)))


@pytest.mark.parametrize("judgments", [{"OTHER": T}, {"A": True}, {"A": []}, []])
def test_unknown_judgment_contract_is_rejected(judgments):
    with pytest.raises(C.ConditionError):
        C.evaluate_condition_graph(pair(), judgments)


def test_separate_records_cannot_fill_each_others_missing_conditions():
    # A=800식 이상, B=1년 이상; 둘 다 만족하는 같은 사업장이 필요하다.
    records = {"site1": {"A": T, "B": F}, "site2": {"A": F, "B": T}}
    result = C.count_matching_records(pair(), records, minimum=1, collection_complete=True)
    assert result.status == F and result.matched_count == 0


def test_two_complete_records_satisfy_count():
    result = C.count_matching_records(pair(), {"site1": {"A": T, "B": T}, "site2": {"A": T, "B": T}},
                                       minimum=2, collection_complete=True)
    assert result.status == T and result.matched_count == 2


@pytest.mark.parametrize(("records", "complete", "minimum", "expected"), [
    ({}, True, 1, F), ({}, False, 1, U),
    ({"site1":{"A":T, "B":T}}, False, 1, T),
    ({"site1":{"A":T, "B":T}}, False, 2, U),
    ({"site1":{"A":T, "B":T}}, True, 2, F),
    ({"site1":{"A":T}}, True, 1, U),
    ({"site1":{"A":T}}, True, 2, F),
])
def test_unknown_records_use_lower_and_upper_bounds(records, complete, minimum, expected):
    assert C.count_matching_records(pair(), records, minimum=minimum, collection_complete=complete).status == expected


@pytest.mark.parametrize("minimum", [True, 0, -1, 1.5])
def test_invalid_count_threshold(minimum):
    with pytest.raises(C.ConditionError):
        C.count_matching_records(pair(), {}, minimum=minimum, collection_complete=True)


@pytest.mark.parametrize("scope", [{}, {"min": 1}, {"min": True, "min_operator": ">="},
    {"min": 5, "min_operator": ">=", "max": 3, "max_operator": "<="},
    {"min": 5, "min_operator": ">", "max": 5, "max_operator": "<="}])
def test_invalid_or_empty_ranges_are_rejected(scope):
    with pytest.raises(C.ConditionError):
        C.AtomicCondition.from_requirement("A", {"type":"PERFORMANCE_AMOUNT", "operator":"RANGE", "value":None,
            "scope":scope}, subject="BIDDER", evidence_ids=("E1",))


def test_valid_explicit_range_can_be_preserved():
    item = C.AtomicCondition.from_requirement("A", {"type":"PERFORMANCE_AMOUNT", "operator":"RANGE", "value":None,
        "scope":{"min":3, "min_operator":">=", "max":5, "max_operator":"<"}}, subject="BIDDER", evidence_ids=("E1",))
    assert json.loads(item.semantic_json)["scope"]["max_operator"] == "<"


@pytest.mark.parametrize("bad", [None, {}, C.ConditionGraph("R", (None,), ()),
    C.ConditionGraph([], (leaf("A"),), (atom("A"),)), C.ConditionGraph("A", [leaf("A")], (atom("A"),))])
def test_malformed_graph_contracts_are_rejected(bad):
    with pytest.raises(C.ConditionError):
        C.validate_graph(bad)
