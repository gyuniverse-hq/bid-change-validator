"""판정이 끝난 골든셋 케이스를 읽어온다. 판정기를 다시 돌리지 않는다.

판정 결과는 이미 있다 — 골든셋 실행기가 고정 commit 에서 돌려 남긴 스냅샷이다.
요건 원문(raw)만 fixture 번들에 있으므로 둘을 이어 붙인다.

여기서 판정기를 다시 부르면 측정할 때마다 판정이 달라질 수 있고, 그러면 초안이
바뀐 이유가 모델 때문인지 판정 때문인지 알 수 없다. 스냅샷을 고정해서 읽는다.

골든셋은 이 저장소에 없다
-------------------------
공고 원문과 회사 프로필이 들어 있는 팀 공용 자료라 저장소에 두지 않는다.
경로를 인자로 받고, 없으면 무엇이 없는지 말하고 멈춘다 — 빈 목록을 돌려주면
"위반 0" 이 측정 성공처럼 보인다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    source_id: str
    notice_title: str
    overall_status: str
    judgments: list[dict[str, Any]]
    raw_by_key: dict[str, str]
    type_by_key: dict[str, str]
    value_by_key: dict[str, object]

    @property
    def flagged(self) -> list[dict[str, Any]]:
        """초안이 숨기면 안 되는 행 — 미달과 확인 필요."""
        return [j for j in self.judgments if j["status"] in ("UNSATISFIED", "UNKNOWN")]


def load_cases(
    *,
    baseline_path: str | Path,
    bundle_path: str | Path,
    include_previous: bool = False,
) -> list[GoldenCase]:
    """`baseline_path` 의 판정 결과와 `bundle_path` 의 요건 원문을 잇는다."""
    baseline_file = Path(baseline_path)
    bundle_file = Path(bundle_path)
    for path, what in ((baseline_file, "판정 결과 스냅샷"), (bundle_file, "fixture 번들")):
        if not path.is_file():
            raise FileNotFoundError(f"{what} 를 찾지 못했습니다: {path}")

    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_file.read_text(encoding="utf-8"))

    source_cases = list(bundle["cases"])
    if include_previous:
        source_cases += bundle.get("previous_cases") or []
    by_id = {case["case_id"]: case for case in source_cases}

    cases: list[GoldenCase] = []
    for entry in baseline["cases"]:
        fixture = by_id.get(entry["case_id"])
        if fixture is None or "result" not in entry:
            continue
        raw_by_key: dict[str, str] = {}
        type_by_key: dict[str, str] = {}
        value_by_key: dict[str, object] = {}
        for item in fixture["canonical_inputs"]:
            requirement = item["requirement"]
            raw_by_key[requirement["requirement_key"]] = requirement.get("raw") or ""
            type_by_key[requirement["requirement_key"]] = requirement["type"]
            value_by_key[requirement["requirement_key"]] = requirement.get("value")
        cases.append(
            GoldenCase(
                case_id=entry["case_id"],
                source_id=entry["source_id"],
                notice_title=fixture["title"],
                overall_status=entry["result"]["overall_status"],
                judgments=entry["result"]["judgments"],
                raw_by_key=raw_by_key,
                type_by_key=type_by_key,
                value_by_key=value_by_key,
            )
        )
    if not cases:
        raise ValueError(
            f"판정이 끝난 케이스를 하나도 읽지 못했습니다 ({baseline_file}). "
            "빈 목록으로 진행하면 '위반 0' 이 측정 성공처럼 보이므로 여기서 멈춥니다."
        )
    return cases
