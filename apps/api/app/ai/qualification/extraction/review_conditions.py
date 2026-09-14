"""조건의 의미와 논리 연결을 보존하는 내부 표현. 자연어를 임의로 파싱하지 않는다.

확인된 원자조건과 명시적 논리 트리를 받는다. 세 값 판정은 논리 계산이며
원문 의미 해석의 정답 보증이 아니다. 기존 HTTP/판정기 계약을 대체하지 않는다.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
import hashlib
import json
import math
from typing import Any

CONDITION_VERSION = "review-conditions-v1"
_STATUSES = frozenset({"SATISFIED", "UNSATISFIED", "UNKNOWN"})
_TYPES = frozenset({"PERFORMANCE_AMOUNT", "PERFORMANCE_COUNT", "INDUSTRY", "REGION",
                    "STAFF", "REGISTRATION_CERTIFICATION", "EXPERIENCE_FIELD", "COMPANY_SIZE"})
_OPERATORS = frozenset({">=", ">", "<=", "<", "=", "MATCH", "RANGE"})
_NODE_OPS = frozenset({"ATOM", "ALL_OF", "ANY_OF", "NOT", "EXEMPT_IF"})


class ConditionError(ValueError):
    """값·원문을 포함하지 않는 고정 진단 코드."""


def _json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError) as error:
        raise ConditionError("INVALID_SEMANTIC_JSON") from error


def _hash(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _id(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConditionError("INVALID_IDENTIFIER")
    return value


def _ids(values: Iterable[str]) -> tuple[str, ...]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes)):
        raise ConditionError("INVALID_IDENTIFIER_LIST")
    return tuple(sorted({_id(value) for value in values}))


@dataclass(frozen=True)
class AtomicCondition:
    atom_id: str
    # 식별/근거를 제외한 의미를 canonical JSON으로 보존해 변경 불가능하게 한다.
    semantic_json: str
    evidence_ids: tuple[str, ...]

    @classmethod
    def from_requirement(cls, atom_id: str, requirement: Mapping[str, Any], *,
                         subject: str, evidence_ids: Iterable[str]) -> AtomicCondition:
        """기존 canonical 요건의 조건 필드를 빠짐없이 의미 지문에 포함한다.

        value만 같다고 같은 요건이 아니다. 연산자/기간/범위/역할/주체도 같아야 한다.
        raw와 source ID는 의미 판정의 대체물이 아니며 별도 evidence에서 보존한다.
        """
        _id(atom_id)
        _id(subject)
        if not isinstance(requirement, Mapping):
            raise ConditionError("INVALID_ATOMIC_REQUIREMENT")
        type_, operator = requirement.get("type"), requirement.get("operator")
        if not isinstance(type_, str) or type_ not in _TYPES:
            raise ConditionError("INVALID_REQUIREMENT_TYPE")
        if not isinstance(operator, str) or operator not in _OPERATORS:
            raise ConditionError("UNRESOLVED_OPERATOR")
        value = requirement.get("value")
        if (operator != "RANGE" and (value is None or isinstance(value, bool)
                or not isinstance(value, (int, float, str)) or value == "")):
            raise ConditionError("UNRESOLVED_VALUE")
        if isinstance(value, float) and not math.isfinite(value):
            raise ConditionError("NON_FINITE_VALUE")
        unit, period = requirement.get("unit"), requirement.get("period_months")
        if unit is not None and (not isinstance(unit, str) or not unit.strip()):
            raise ConditionError("INVALID_UNIT")
        if period is not None and (isinstance(period, bool) or not isinstance(period, (int, float))
                or not math.isfinite(period) or period < 0):
            raise ConditionError("INVALID_PERIOD")
        scope = requirement.get("scope", {})
        if not isinstance(scope, Mapping):
            raise ConditionError("INVALID_SCOPE")
        if operator == "RANGE":
            limits = [("min", (">=", ">")), ("max", ("<=", "<"))]
            if not any(scope.get(name) is not None for name, _ in limits):
                raise ConditionError("EMPTY_RANGE")
            for name, ops in limits:
                bound = scope.get(name)
                if bound is not None and (isinstance(bound, bool) or not isinstance(bound, (int, float))
                        or not math.isfinite(bound) or scope.get(name + "_operator") not in ops):
                    raise ConditionError("INVALID_RANGE_BOUND")
            lower, upper = scope.get("min"), scope.get("max")
            if lower is not None and upper is not None and (lower > upper or
                    (lower == upper and (scope["min_operator"] == ">" or scope["max_operator"] == "<"))):
                raise ConditionError("EMPTY_RANGE")
        role = requirement.get("requirement_role", "mandatory")
        required = requirement.get("required", role == "mandatory")
        if role not in ("mandatory", "preferred", "informational") or not isinstance(required, bool):
            raise ConditionError("INVALID_REQUIREMENT_ROLE")
        if required != (role == "mandatory"):
            raise ConditionError("INCONSISTENT_REQUIRED_FLAG")
        if requirement.get("condition_complexity", "simple") != "simple":
            raise ConditionError("COMPOSITE_CANNOT_BE_AN_ATOM")
        refs = _ids(evidence_ids)
        if not refs:
            raise ConditionError("MISSING_ATOM_EVIDENCE")
        # 새 의미 필드를 도입할 때 알 수 없는 필드를 조용히 버리지 않는다.
        permitted = {"type", "operator", "value", "unit", "period_months", "scope",
            "requirement_role", "condition_complexity", "required", "raw", "confidence",
            "requirement_key", "requirement_group_key", "group_operator", "notice_version_id",
            "evidence_keys"}
        if set(requirement) - permitted:
            raise ConditionError("UNRECOGNIZED_REQUIREMENT_FIELDS")
        payload = {"type": type_, "operator": operator, "value": value,
            "unit": requirement.get("unit"), "period_months": requirement.get("period_months"),
            "scope": dict(scope), "requirement_role": role, "required": required,
            "condition_complexity": "simple", "subject": subject}
        return cls(atom_id, _json(payload), refs)

    @property
    def semantic_sha256(self) -> str:
        return _hash({"version": CONDITION_VERSION, "predicate": json.loads(self.semantic_json)})


@dataclass(frozen=True)
class ConditionNode:
    node_id: str
    operator: str
    children: tuple[str, ...] = ()
    atom_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionGraph:
    root_id: str
    nodes: tuple[ConditionNode, ...]
    atoms: tuple[AtomicCondition, ...]


def validate_graph(graph: ConditionGraph, *, available_evidence_ids: Iterable[str] | None = None) -> None:
    """누락·순환·고립을 거부한다. 참조의 존재와 자연어 의미는 별도 검사다."""
    if (not isinstance(graph, ConditionGraph) or not isinstance(graph.nodes, tuple)
            or not isinstance(graph.atoms, tuple) or not graph.nodes or len(graph.nodes) > 512):
        raise ConditionError("INVALID_GRAPH_SIZE")
    if (any(not isinstance(node, ConditionNode) for node in graph.nodes)
            or any(not isinstance(atom, AtomicCondition) for atom in graph.atoms)):
        raise ConditionError("INVALID_GRAPH_ENTRY")
    _id(graph.root_id)
    nodes = {_id(node.node_id): node for node in graph.nodes}
    atoms = {_id(atom.atom_id): atom for atom in graph.atoms}
    if len(nodes) != len(graph.nodes) or len(atoms) != len(graph.atoms):
        raise ConditionError("DUPLICATE_GRAPH_IDENTIFIER")
    if graph.root_id not in nodes:
        raise ConditionError("MISSING_ROOT")
    pool = set(_ids(available_evidence_ids)) if available_evidence_ids is not None else None
    for atom in atoms.values():
        try:
            payload = json.loads(atom.semantic_json)
            subject = payload.pop("subject")
            checked = AtomicCondition.from_requirement(atom.atom_id, payload, subject=subject,
                                                       evidence_ids=atom.evidence_ids)
        except (ValueError, TypeError, KeyError, AttributeError) as error:
            raise ConditionError("INVALID_ATOM") from error
        if checked != atom:
            raise ConditionError("NON_CANONICAL_ATOM")
        if pool is not None and not set(atom.evidence_ids) <= pool:
            raise ConditionError("UNKNOWN_EVIDENCE")
    for node in nodes.values():
        if not isinstance(node.operator, str) or node.operator not in _NODE_OPS or not isinstance(node.children, tuple):
            raise ConditionError("INVALID_NODE_OPERATOR")
        if any(not isinstance(child, str) or child not in nodes for child in node.children):
            raise ConditionError("UNRESOLVED_CHILD")
        if len(node.children) != len(set(node.children)):
            raise ConditionError("DUPLICATE_CHILD_REFERENCE")
        if node.operator == "ATOM":
            if node.children or not isinstance(node.atom_id, str) or node.atom_id not in atoms:
                raise ConditionError("INVALID_ATOM_NODE")
        elif node.atom_id is not None:
            raise ConditionError("GROUP_HAS_ATOM")
        elif ((node.operator in {"ALL_OF", "ANY_OF"} and len(node.children) < 2)
                or (node.operator == "NOT" and len(node.children) != 1)
                or (node.operator == "EXEMPT_IF" and len(node.children) != 2)):
            raise ConditionError("INVALID_NODE_ARITY")
        refs = _ids(node.evidence_ids)
        if node.evidence_ids != refs or (node.operator != "ATOM" and not refs):
            raise ConditionError("MISSING_OR_NON_CANONICAL_RELATION_EVIDENCE")
        if pool is not None and not set(refs) <= pool:
            raise ConditionError("UNKNOWN_EVIDENCE")
    visited: set[str] = set()
    visiting: set[str] = set()
    used_atoms: set[str] = set()
    heights: dict[str, int] = {}

    def walk(key: str, depth: int) -> None:
        if depth > 32:
            raise ConditionError("GRAPH_TOO_DEEP")
        if key in visiting:
            raise ConditionError("CYCLIC_GRAPH")
        if key in visited:
            if depth + heights[key] > 32:
                raise ConditionError("GRAPH_TOO_DEEP")
            return
        visiting.add(key)
        node = nodes[key]
        if node.atom_id is not None:
            used_atoms.add(node.atom_id)
        for child in node.children:
            walk(child, depth + 1)
        heights[key] = max((heights[child] + 1 for child in node.children), default=0)
        visiting.remove(key)
        visited.add(key)
    walk(graph.root_id, 0)
    if visited != set(nodes) or used_atoms != set(atoms):
        raise ConditionError("ORPHANED_CONDITION")


def semantic_fingerprint(graph: ConditionGraph) -> str:
    """동일 내용의 ID·나열 순서는 무시하되 AND/OR·주체·조건 범위는 보존한다.

    버전 간 같은 요건을 연결하는 키가 아니라 의미 내용의 지문이다.
    """
    validate_graph(graph)
    nodes = {node.node_id: node for node in graph.nodes}
    atoms = {atom.atom_id: atom for atom in graph.atoms}
    memo: dict[str, str] = {}
    def digest(key: str) -> str:
        if key in memo:
            return memo[key]
        node = nodes[key]
        if node.operator == "ATOM":
            value = atoms[node.atom_id].semantic_sha256
        else:
            children = [digest(child) for child in node.children]
            if node.operator in {"ALL_OF", "ANY_OF"}:
                children = sorted(set(children))
            value = _hash({"operator": node.operator, "children": children})
        memo[key] = value
        return value
    return _hash({"version": CONDITION_VERSION, "root": digest(graph.root_id)})


def deduplicate_atoms(graph: ConditionGraph) -> ConditionGraph:
    """동일 의미의 원자를 공유해도 각 논리 그룹의 참조는 삭제하지 않는다.

    (A OR B) AND (A OR C)의 두 A는 값을 공유할 수 있어도 연결은 둘 다 필요하다.
    """
    validate_graph(graph)
    grouped: dict[str, AtomicCondition] = {}
    aliases: dict[str, str] = {}
    for atom in graph.atoms:
        key = "ATOM-" + atom.semantic_sha256
        aliases[atom.atom_id] = key
        if key in grouped:
            old = grouped[key]
            if old.semantic_json != atom.semantic_json:
                raise ConditionError("SEMANTIC_HASH_COLLISION")
            grouped[key] = replace(old, evidence_ids=_ids((*old.evidence_ids, *atom.evidence_ids)))
        else:
            grouped[key] = replace(atom, atom_id=key)
    result = ConditionGraph(graph.root_id,
        tuple(replace(node, atom_id=aliases[node.atom_id]) if node.operator == "ATOM" else node
              for node in graph.nodes), tuple(grouped[key] for key in sorted(grouped)))
    validate_graph(result)
    return result


def _all(values: list[str]) -> str:
    if "UNSATISFIED" in values:
        return "UNSATISFIED"
    return "UNKNOWN" if "UNKNOWN" in values else "SATISFIED"


def _any(values: list[str]) -> str:
    if "SATISFIED" in values:
        return "SATISFIED"
    return "UNKNOWN" if "UNKNOWN" in values else "UNSATISFIED"


def evaluate_condition_graph(graph: ConditionGraph, judgments: Mapping[str, str]) -> str:
    """이미 판정한 원자값을 합성한다. 미지정은 UNKNOWN이며 무관한 키는 거부한다.

    EXEMPT_IF children=(requirement, exemption): exemption이 참이면 해당 requirement를 면제한다.
    일반적인 예외 문장을 자동으로 이 연산자로 변환해도 된다는 뜻은 아니다.
    """
    validate_graph(graph)
    atom_ids = {atom.atom_id for atom in graph.atoms}
    if not isinstance(judgments, Mapping) or not set(judgments) <= atom_ids:
        raise ConditionError("UNKNOWN_ATOM_JUDGMENT")
    if any(not isinstance(value, str) or value not in _STATUSES for value in judgments.values()):
        raise ConditionError("INVALID_JUDGMENT_STATUS")
    nodes = {node.node_id: node for node in graph.nodes}
    memo: dict[str, str] = {}
    def value(key: str) -> str:
        if key in memo:
            return memo[key]
        node = nodes[key]
        if node.operator == "ATOM":
            result = judgments.get(node.atom_id, "UNKNOWN")
        else:
            children = [value(child) for child in node.children]
            if node.operator == "ALL_OF":
                result = _all(children)
            elif node.operator in {"ANY_OF", "EXEMPT_IF"}:
                result = _any(children)
            else:
                result = {"SATISFIED": "UNSATISFIED", "UNSATISFIED": "SATISFIED",
                          "UNKNOWN": "UNKNOWN"}[children[0]]
        memo[key] = result
        return result
    return value(graph.root_id)


@dataclass(frozen=True)
class RecordCountResult:
    status: str
    matched_count: int
    unknown_count: int
    possible_upper_count: int | None


def count_matching_records(graph: ConditionGraph, records: Mapping[str, Mapping[str, str]], *,
                           minimum: int, collection_complete: bool) -> RecordCountResult:
    """각 실적에 같은 조건 전체를 적용한 뒤 센다. 다른 실적의 일부로 조건을 채우지 않는다.

    records의 키는 고유한 실적/사업장 ID이며 값은 동일 실적의 원자별 판정이다.
    이 함수는 날짜·금액·기업 DB를 직접 비교하지 않는다. 없는 사실은 UNKNOWN으로 제공한다.
    """
    validate_graph(graph)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise ConditionError("INVALID_MINIMUM_COUNT")
    if not isinstance(collection_complete, bool) or not isinstance(records, Mapping):
        raise ConditionError("INVALID_RECORD_COLLECTION")
    statuses = []
    for key, judgments in records.items():
        _id(key)
        statuses.append(evaluate_condition_graph(graph, judgments))
    matched = statuses.count("SATISFIED")
    unknown = statuses.count("UNKNOWN")
    upper = matched + unknown if collection_complete else None
    status = ("SATISFIED" if matched >= minimum else
              "UNSATISFIED" if upper is not None and upper < minimum else "UNKNOWN")
    return RecordCountResult(status, matched, unknown, upper)
