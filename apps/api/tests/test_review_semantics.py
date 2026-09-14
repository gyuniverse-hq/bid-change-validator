"""실제 후보/계획/실행/컴파일/조건 모듈, 모델 I/O만 대역인 연결 테스트."""
from __future__ import annotations

import copy
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
ROOT = "_qualification_semantic_tests"
# 앱 전체 SDK 초기화만 건너뛴다. 실제 모듈의 함수/클래스는 교체하지 않는다.
for suffix, path in (("", APP), (".ai", APP / "ai"), (".ai.qualification", APP / "ai/qualification"),
                     (".ai.qualification.extraction", APP / "ai/qualification/extraction"),
                     (".qualification", APP / "qualification"), (".qualification.rules", APP / "qualification/rules")):
    name = ROOT + suffix
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(path)]
        sys.modules[name] = package
PREFIX = ROOT + ".ai.qualification.extraction"
sem = importlib.import_module(PREFIX + ".review_semantics")
runtime = importlib.import_module(PREFIX + ".review_execution")
planning = importlib.import_module(PREFIX + ".review_plan")
logic = importlib.import_module(PREFIX + ".review_conditions")


def source(key, text):
    return {"source_candidate_id": key, "quote": text}


def atom(key, aid="a", text="업종코드 1450 등록 업체", value="1450", type_="INDUSTRY", **changes):
    return {"atom_id": aid, "type": type_, "subject": "BIDDER", "predicate_source": source(key, text),
        "value_role": sem._VALUE_ROLES[type_], "value_source": source(key, value), "qualifiers": [],
        "aggregation": "UNSPECIFIED", "aggregation_source": None, **changes}


def qualifier(key, role, text, anchor=None, anchor_text=None):
    return {"role": role, "source": source(key, text), "anchor": anchor,
            "anchor_source": source(key, anchor_text) if anchor_text else None}


def leaf(aid, nid=None):
    return {"node_id": nid or "n" + aid, "operator": "ATOM", "atom_id": aid, "children": [], "evidence": []}


def group(key, text, op, children, nid="root"):
    return {"node_id": nid, "operator": op, "atom_id": None, "children": children, "evidence": [source(key, text)]}


def decision(key, atoms=None, nodes=None, root="na", **changes):
    return {"candidate_id": key, "status": "REQUIREMENT", "reason": None, "basis": "SELF_CONTAINED",
            "role": "mandatory", "atoms": [atom(key)] if atoms is None else atoms, "nodes": [leaf("a")] if nodes is None else nodes, "root_id": root, **changes}


def not_requirement(key):
    return decision(key, status="NOT_REQUIREMENT", reason="표제 또는 안내", atoms=[], nodes=[], root_id=None)


def plan(text="업종코드 1450 등록 업체", **kwargs):
    inv = planning.build_review_inventory([{"document_id": "D1", "block_index": 0, "text": text,
        "page": 1, "source_sha256": "a" * 64}], notice_version_id="V1")
    return planning.plan_review_requests(inv, **kwargs)


class Model:
    model = "fake-model-not-live"

    def __init__(self, handler):
        self.handler = handler
        self.calls = []

    def __call__(self, prompt, body, schema):
        payload = json.loads(body)
        self.calls.append((prompt, payload, copy.deepcopy(schema)))
        return self.handler(payload, len(self.calls))


def run(text="업종코드 1450 등록 업체", factory=None, **options):
    p = plan(text)
    model = Model(lambda payload, n: {"decisions": [factory(k) if factory else decision(k)
                                                  for k in payload["target_candidate_ids"]]})
    result = runtime.execute_review_plan(p, structured_extract=model, options=runtime.ReviewOptions(**options),
                                         response_contract=sem.semantic_response_contract())
    return result, model


def complex_case(key):
    a = "가공업(1257)을 등록"
    cert = "ISO 9001 인증을 보유한 업체"
    b = "운반업(1227)을 등록한 업체"
    both = f"{a}하고 {cert}"
    text = f"({both}) 또는 {b}"
    atoms = [atom(key, "a", a, "1257"), atom(key, "cert", cert, "ISO 9001", "REGISTRATION_CERTIFICATION"),
             atom(key, "b", b, "1227")]
    nodes = [leaf("a"), leaf("cert"), leaf("b"), group(key, both, "ALL_OF", ["na", "ncert"], "both"),
             group(key, text, "ANY_OF", ["both", "nb"])]
    return text, decision(key, atoms, nodes, "root")


def compiled_complex():
    text, _ = complex_case("dummy")
    result, _ = run(text, lambda key: complex_case(key)[1])
    assert result.coverage.coverage_status == "COMPLETE", result.audit()
    return result.decisions[0]


def rejected(factory, text="업종코드 1450 등록 업체"):
    result, model = run(text, factory)
    assert result.coverage.coverage_status == "INVALID", result.audit()
    assert not result.decisions
    assert len(model.calls) == 1
    return result.events[0]["rejected"][0]["code"]


def test_schema_closed_required_and_no_generated_numeric_or_coordinate_fields():
    schema = sem.semantic_response_schema()["schema"]
    def walk(item):
        if isinstance(item, dict):
            if item.get("type") == "object":
                assert item["additionalProperties"] is False
                assert set(item["required"]) == set(item["properties"])
            for child in item.values():
                walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)
    walk(schema)
    encoded = json.dumps(schema)
    for field in ('"start_offset"', '"value"', '"period_months"', '"raw"'):
        assert field not in encoded


def test_schema_is_valid_and_normal_response_matches():
    jsonschema = pytest.importorskip("jsonschema")
    schema = sem.semantic_response_schema()["schema"]
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate({"decisions": [decision("test")]}, schema)


def test_simple_value_is_resolved_from_source_and_uses_contract():
    result, model = run()
    d = result.decisions[0]
    assert result.coverage.coverage_status == "COMPLETE"
    assert not d.pending_codes
    assert json.loads(d.atoms[0].requirement_json)["value"] == "1450"
    assert model.calls[0][0] == sem.SEMANTIC_PROMPT
    assert result.audit()["response_version"] == sem.SEMANTIC_VERSION
    assert result.audit()["decision_statuses"][0]["condition_count"] == 1
    assert '업종코드' not in json.dumps(d.audit(), ensure_ascii=False)


def test_nested_logic_reaches_existing_condition_graph_without_flattening():
    d = compiled_complex()
    assert logic.evaluate_condition_graph(d.graph, {"a": "SATISFIED", "cert": "UNSATISFIED", "b": "UNSATISFIED"}) == "UNSATISFIED"
    assert logic.evaluate_condition_graph(d.graph, {"a": "UNSATISFIED", "cert": "UNKNOWN", "b": "SATISFIED"}) == "SATISFIED"


@pytest.mark.parametrize('amount,expected', [('5천만원 이상', 50_000_000), ('1.3억원 이상', 130_000_000),
                                              ('200,000,000원 이상', 200_000_000)])
def test_amount_is_parsed_by_code(amount, expected):
    text = f"{amount} 단일 실적 보유"
    result, _ = run(text, lambda k: decision(k, [atom(k, text=text, value=amount, type_="PERFORMANCE_AMOUNT",
                     aggregation="MAX", aggregation_source=source(k, "단일"))]))
    assert result.coverage.coverage_status == "COMPLETE"
    assert json.loads(result.decisions[0].atoms[0].requirement_json)["value"] == expected


def test_lookback_and_duration_are_not_merged():
    text = "입찰공고일 기준 최근 2년 이내 1일 평균 800식 이상을 1년 이상 운영한 사업장 2개 이상 실적"
    def make(k):
        return decision(k, [atom(k, text=text, value="2개 이상", type_="PERFORMANCE_COUNT", qualifiers=[
            qualifier(k, "LOOKBACK_WINDOW", "최근 2년 이내", "NOTICE_DATE", "입찰공고일 기준"),
            qualifier(k, "OPERATION_DURATION", "1년 이상"), qualifier(k, "DAILY_VOLUME", "1일 평균 800식 이상")])])
    result, _ = run(text, make)
    assert result.coverage.coverage_status == "COMPLETE", result.audit()
    d = result.decisions[0]
    req = json.loads(d.atoms[0].requirement_json)
    assert not d.pending_codes
    assert req["period_months"] == 24
    filters = {f["role"]: f["value"] for f in req["scope"]["review_semantics"]["record_filters"]}
    assert filters == {"OPERATION_DURATION": 12, "DAILY_VOLUME": 800}


@pytest.mark.parametrize('role', ['BUDGET_AMOUNT', 'LOOKBACK_WINDOW', 'OPERATION_DURATION', None, []])
def test_wrong_value_role_is_rejected(role):
    assert rejected(lambda k: decision(k, [atom(k, value_role=role)])) == "TYPE_VALUE_ROLE_MISMATCH"


@pytest.mark.parametrize('change', [{"value": 999}, {"start_offset": 0}, {"raw": "created"}])
def test_model_cannot_supply_new_numeric_value_or_location(change):
    assert rejected(lambda k: decision(k, [{**atom(k), **change}])) == "INVALID_FIELDS"


def test_budget_cannot_be_attached_as_performance_amount():
    text = "사업 예산 5억원 이상"
    assert rejected(lambda k: decision(k, [atom(k, text=text, value="5억원 이상", type_="PERFORMANCE_AMOUNT")]), text) == "BUDGET_IS_NOT_PERFORMANCE"


def test_other_clause_value_is_not_bound_to_predicate():
    text = "실적 1억원 이상을 보유한 업체이며 사업 예산 5억원 이상"
    assert rejected(lambda k: decision(k, [atom(k, text="실적 1억원 이상을 보유한 업체", value="5억원 이상",
                                              type_="PERFORMANCE_AMOUNT")]), text) == "QUOTE_NOT_IN_SOURCE"


def test_mandatory_certification_omission_is_visible():
    text = "업종코드 1450 등록 업체이며 ISO 9001 인증 보유"
    result, _ = run(text, lambda k: decision(k))
    assert "UNREPRESENTED_EXPLICIT_VALUE" in result.decisions[0].pending_codes


def test_or_omission_is_visible_even_if_all_codes_are_retained():
    text = "가공업(1257) 등록 또는 운반업(1227) 등록"
    # 관계 근거도 '또는'만 있으므로 ALL_OF를 허용하지 않는다.
    assert rejected(lambda k: decision(k, [atom(k, 'a', '가공업(1257) 등록', '1257'),
        atom(k, 'b', '운반업(1227) 등록', '1227')], [leaf('a'), leaf('b'), group(k,text,'ALL_OF',['na','nb'])], 'root'), text) == 'RELATION_CUE_MISSING'


@pytest.mark.parametrize('change', [lambda d: d.update(root_id='missing'),
    lambda d: d['nodes'].append(leaf('a','orphan')), lambda d: d['nodes'].append(copy.deepcopy(d['nodes'][0])),
    lambda d: d['atoms'].append(copy.deepcopy(d['atoms'][0]))])
def test_invalid_graph_is_quarantined(change):
    def make(k):
        d = decision(k); change(d); return d
    rejected(make)


def test_unresolved_anchor_is_not_today():
    text = "최근 3년 이내 5천만원 이상 실적"
    result, _ = run(text, lambda k: decision(k, [atom(k, text=text, value='5천만원 이상', type_='PERFORMANCE_AMOUNT',
        qualifiers=[qualifier(k,'LOOKBACK_WINDOW','최근 3년 이내')])]))
    assert 'UNSPECIFIED_TIME_ANCHOR' in result.decisions[0].pending_codes


def test_anchor_needs_source_correspondence():
    text = "입찰공고일 기준 최근 3년 이내 5천만원 이상 실적"
    rejected(lambda k: decision(k, [atom(k,text=text,value='5천만원 이상',type_='PERFORMANCE_AMOUNT',qualifiers=[
        qualifier(k,'LOOKBACK_WINDOW','최근 3년 이내','CONTRACT_START','입찰공고일 기준')])]), text)


def test_unsupported_qualifier_role_does_not_silently_disappear():
    rejected(lambda k: decision(k,[atom(k,qualifiers=[qualifier(k,'OPERATION_DURATION','1450')])]))


def test_source_quote_normalization_uses_original_text():
    text = 'ISO 9001※ 인증 보유 업체'
    result, _ = run(text, lambda k: decision(k,[atom(k,text='ISO9001 인증 보유 업체',value='ISO9001',type_='REGISTRATION_CERTIFICATION')]))
    assert result.coverage.coverage_status == 'COMPLETE', result.audit()
    assert json.loads(result.decisions[0].atoms[0].requirement_json)['raw'] == text


def test_missing_retry_preserves_graph_response_contract():
    p = plan('3. 참가자격\n가. 업종코드 1450 등록 업체')
    head, target = p.target_candidate_ids
    model = Model(lambda payload,n: {'decisions': [not_requirement(head)] if n==1 else [decision(target)]})
    result = runtime.execute_review_plan(p,structured_extract=model,response_contract=sem.semantic_response_contract())
    assert result.coverage.coverage_status == 'COMPLETE'
    assert model.calls[1][1]['target_candidate_ids'] == [target]
    assert all(c[2]['name'] == 'qualification_review_graph_v1' for c in model.calls)


def test_old_slots_contract_remains_default():
    p = plan()
    model = Model(lambda payload,n: {'decisions': [{'candidate_id': p.target_candidate_ids[0],
        'status':'REQUIREMENT', 'reason':None, 'slots':[{'type':'업종요건','basis':'SELF_CONTAINED',
        'fields':[{'name':'업종_raw',**source(p.target_candidate_ids[0],'1450')}]}]}]})
    result = runtime.execute_review_plan(p,structured_extract=model)
    assert result.coverage.coverage_status == 'COMPLETE'
    assert result.audit()['response_version'] == runtime.RESPONSE_VERSION
    assert result.audit()['decision_statuses'][0]['slot_count'] == 1


def test_clause_context_does_not_imply_applicability():
    result, _ = run(factory=lambda k: decision(k,basis='CONTEXT_DEPENDENT'))
    assert result.decisions[0].pending_codes == ('CONTEXT_APPLICABILITY_PENDING',)


def test_renumbering_nodes_and_atoms_preserves_semantic_fingerprint():
    text,_ = complex_case('dummy')
    def changed(k):
        d = complex_case(k)[1]
        for a in d['atoms']: a['atom_id'] += '2'
        for n in d['nodes']:
            n['node_id'] += '2'; n['children']=[x+'2' for x in n['children']]
            if n['atom_id']: n['atom_id'] += '2'
        d['root_id'] += '2'; d['atoms'].reverse(); d['nodes'].reverse()
        return d
    result,_ = run(text,changed)
    assert sem.semantic_fingerprint(result.decisions[0].graph) == sem.semantic_fingerprint(compiled_complex().graph)


def test_responses_and_inputs_are_not_mutated():
    p=plan(); wire={'decisions':[decision(p.target_candidate_ids[0])]}; original=copy.deepcopy(wire)
    runtime.execute_review_plan(p,structured_extract=Model(lambda p,n:wire),response_contract=sem.semantic_response_contract())
    assert wire == original


@pytest.mark.parametrize('status',['UNRESOLVED','NEEDS_CONTEXT','NOT_REQUIREMENT'])
def test_non_requirement_has_empty_graph_and_no_retry(status):
    result,model=run(factory=lambda k:decision(k,status=status,reason='검토 필요',atoms=[],nodes=[],root_id=None))
    assert len(model.calls)==1
    assert result.decisions[0].graph is None
