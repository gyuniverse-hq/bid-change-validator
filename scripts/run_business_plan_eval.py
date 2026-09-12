"""사업계획서 초안이 확정된 판정 결과에 충실한지 측정한다.

    골든셋 판정 JSON ─[코드 조판]→ 프롬프트 ─[모델]→ 초안 ─[코드 검사]→ 위반 수

모델은 가운데 한 번만 끼어든다. 판정도 조판도 검사도 코드라, 반복 실행에서 나오는
차이는 전부 모델 몫이다.

왜 반복 실행하나
----------------
모델은 같은 입력에도 매번 다르게 쓴다. 한 번 돌린 "누락 0" 은 다음 실행에서
"누락 2" 가 될 수 있다. 평균만 남기면 "3번 중 1번 누락" 과 "매번 33% 누락" 을
구분하지 못하는데, 앞은 불안정성 문제이고 뒤는 성능 문제라 대응이 다르다.
그래서 개별 값을 함께 남긴다.

실행
----
    python scripts/run_business_plan_eval.py \
        --golden-root "<골든셋 폴더>" \
        --narration-root apps/api/app/ai/narration \
        --runs 3

골든셋(공고 원문·회사 프로필)은 팀 공용 자료라 이 저장소에 없다. 경로를 넘겨야 한다.
`--dry-run` 은 모델을 부르지 않고 조판·검사 경로만 확인한다. 이때는 일부러 규칙을
어긴 초안을 넣으므로 위반이 쏟아져야 정상이다.
"""

from __future__ import annotations

import argparse
import collections
import importlib
import importlib.util
import json
import os
import sys
from datetime import datetime
from datetime import timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = REPO_ROOT / "apps" / "api"

sys.path.insert(0, str(API_ROOT))

from app.ai.quality_eval.business_plan import INPUT_SETS  # noqa: E402
from app.ai.quality_eval.business_plan import check_draft  # noqa: E402
from app.ai.quality_eval.business_plan import derive_content_hints  # noqa: E402
from app.ai.quality_eval.business_plan import parse_qualification_items  # noqa: E402
from app.ai.quality_eval.business_plan import render_briefing  # noqa: E402
from app.ai.quality_eval.business_plan import verify_round_trip  # noqa: E402
from app.ai.quality_eval.business_plan.dataset import load_cases  # noqa: E402


def load_generator(narration_root: Path):
    """측정 대상 초안 생성기를 읽어온다.

    `app.ai.narration` 이 아직 develop 에 없고 작업 브랜치에만 있을 수 있다. 그
    브랜치를 체크아웃하거나 리베이스하면 거기서 작업 중인 사람의 변경을 건드리게
    되므로, 패키지 경로만 그 디렉터리로 갈아 끼우고 읽기만 한다.
    """
    if not (narration_root / "business_plan.py").is_file():
        raise SystemExit(
            f"초안 생성기를 찾지 못했습니다: {narration_root}\n"
            "--narration-root 로 business_plan.py 가 있는 디렉터리를 지정하세요."
        )
    importlib.import_module("app.ai")
    spec = importlib.util.spec_from_file_location(
        "app.ai.narration",
        narration_root / "__init__.py",
        submodule_search_locations=[str(narration_root)],
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules["app.ai.narration"] = package
    spec.loader.exec_module(package)
    return importlib.import_module("app.ai.narration.business_plan")


def load_env(env_file: Path) -> None:
    """`.env` 를 직접 읽는다 — 제품 설정 로더를 끌어오면 DB 설정까지 따라온다."""
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--golden-root", type=Path, required=True,
                    help="골든셋 폴더 (fixture_bundle.json 과 results/ 가 있는 곳)")
    ap.add_argument("--baseline", type=Path, default=None,
                    help="판정 결과 스냅샷. 기본값은 --golden-root/results 안의 baseline 파일")
    ap.add_argument("--narration-root", type=Path,
                    default=API_ROOT / "app" / "ai" / "narration")
    ap.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0, help="케이스 수 제한 (0=전체)")
    ap.add_argument("--input-sets", default=",".join(INPUT_SETS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", type=Path, default=None,
                    help="결과 JSON 을 쓸 폴더 (기본: --golden-root/results)")
    args = ap.parse_args()

    bundle_path = args.golden_root / "fixture_bundle.json"
    baseline_path = args.baseline
    if baseline_path is None:
        candidates = sorted((args.golden_root / "results").glob("*baseline*.json"))
        if not candidates:
            raise SystemExit(
                f"판정 결과 스냅샷을 찾지 못했습니다: {args.golden_root / 'results'}/*baseline*.json\n"
                "--baseline 으로 직접 지정하세요."
            )
        baseline_path = candidates[-1]

    load_env(args.env_file)
    module = load_generator(args.narration_root)
    generate = module.generate_business_plan_draft
    make_inputs = module.BusinessPlanInputs

    cases = load_cases(baseline_path=baseline_path, bundle_path=bundle_path)
    if args.limit:
        cases = cases[: args.limit]
    input_names = [name.strip() for name in args.input_sets.split(",") if name.strip()]

    if args.dry_run:
        def narrate(_system: str, _body: str) -> str:
            # 아무 규칙도 지키지 않는 초안. 검사기가 위반을 쏟아내야 정상이다.
            return "# 1. 사업 이해 및 제안 목표\n초안입니다.\n"
    else:
        from app.ai.providers.openai import OpenAINarrator

        narrator = OpenAINarrator(model=args.model)

        def narrate(system: str, body: str) -> str:
            return narrator(system, body)

    records: list[dict] = []
    for case in cases:
        briefing = render_briefing(
            case.judgments, case.overall_status, case.raw_by_key, case.type_by_key,
            notice_title=case.notice_title,
        )
        # 조판이 행을 빠뜨리면 누락률이 모델이 아니라 조판기를 재게 된다.
        verify_round_trip(briefing, case.judgments, case.type_by_key)
        items = parse_qualification_items(briefing)
        flagged_labels = {
            label
            for (label, _status), judgment in zip(items, case.judgments)
            if judgment["status"] in ("UNSATISFIED", "UNKNOWN")
        }
        # 라벨을 안 쓰고 내용으로만 적은 경우를 '숨김'과 가르려면 힌트가 필요하다.
        content_hints = {
            label: derive_content_hints(
                case.value_by_key.get(judgment["requirement_key"]),
                case.raw_by_key.get(judgment["requirement_key"], ""),
            )
            for (label, _status), judgment in zip(items, case.judgments)
        }

        for input_name in input_names:
            payload = make_inputs(**INPUT_SETS[input_name])
            supplied = f"{briefing}\n{payload.render()}"
            for run_index in range(args.runs):
                draft = generate(
                    briefing,
                    payload,
                    notice_id=case.source_id,
                    judgment_count=len(case.judgments),
                    flagged_clause_count=len(case.flagged),
                    narrate=narrate,
                )
                report = check_draft(
                    draft.text, case_id=case.case_id, items=items,
                    flagged_labels=flagged_labels, supplied_text=supplied,
                    content_hints=content_hints,
                )
                records.append({
                    "case_id": case.case_id,
                    "source_id": case.source_id,
                    "input_set": input_name,
                    "run": run_index,
                    "draft_status": draft.status,
                    "generator_warnings": list(getattr(draft, "warnings", []) or []),
                    "flagged_total": report.flagged_total,
                    "omission": report.count("OMISSION"),
                    "misstated": report.count("MISSTATED"),
                    "contradiction": report.count("CONTRADICTION"),
                    "label_deviation": report.count("LABEL_DEVIATION"),
                    "sections_ok": report.section_ok,
                    "check_markers": report.check_marker_count,
                    "number_candidates": report.number_candidates,
                    "draft_chars": report.draft_chars,
                    "violations": [
                        {"kind": v.kind, "label": v.requirement_label, "detail": v.detail}
                        for v in report.violations
                    ],
                    "draft_text": draft.text,
                })
                print(
                    f"  {case.case_id:<10}{input_name:<9}run{run_index}  "
                    f"누락 {report.count('OMISSION')}/{report.flagged_total}  "
                    f"오기 {report.count('MISSTATED')}  모순 {report.count('CONTRADICTION')}  "
                    f"목차 {'OK' if report.section_ok else 'NG'}  {report.draft_chars}자",
                    flush=True,
                )

    flagged_sum = sum(r["flagged_total"] for r in records)
    summary = {
        "records": len(records),
        "flagged_rows_total": flagged_sum,
        "omission_total": sum(r["omission"] for r in records),
        "misstated_total": sum(r["misstated"] for r in records),
        "contradiction_total": sum(r["contradiction"] for r in records),
        "label_deviation_total": sum(r["label_deviation"] for r in records),
        "omission_rate": (
            sum(r["omission"] for r in records) / flagged_sum if flagged_sum else None
        ),
        "sections_ok_rate": (
            sum(1 for r in records if r["sections_ok"]) / len(records) if records else None
        ),
        # 케이스별 개별 값도 남긴다. 평균만 두면 "3번 중 1번" 과 "매번 33%" 가 같아 보인다.
        "unsafe_by_case_run": {
            case_id: [
                r["omission"] + r["misstated"] + r["contradiction"]
                for r in records if r["case_id"] == case_id
            ]
            for case_id in dict.fromkeys(r["case_id"] for r in records)
        },
        "by_input_set": {
            name: {
                "omission": sum(r["omission"] for r in records if r["input_set"] == name),
                "misstated": sum(r["misstated"] for r in records if r["input_set"] == name),
                "contradiction": sum(r["contradiction"] for r in records if r["input_set"] == name),
                "label_deviation": sum(r["label_deviation"] for r in records if r["input_set"] == name),
                "flagged": sum(r["flagged_total"] for r in records if r["input_set"] == name),
            }
            for name in input_names
        },
        "generator_warnings": dict(collections.Counter(
            warning for r in records for warning in r["generator_warnings"]
        )),
    }

    out_dir = args.out or (args.golden_root / "results")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"business_plan_conformance_{'dry' if args.dry_run else 'live'}_{stamp}.json"
    path.write_text(
        json.dumps(
            {
                "executed_at": stamp,
                "runs": args.runs,
                "dry_run": args.dry_run,
                "baseline": str(baseline_path),
                "narration_root": str(args.narration_root),
                "model": args.model or os.getenv("OPENAI_MODEL_DEFAULT"),
                "summary": summary,
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n-> {path}")
    # 안전 지표가 0 이 아니면 실패로 끝낸다 — CI 에 걸 수 있게.
    unsafe = (
        summary["omission_total"] + summary["misstated_total"] + summary["contradiction_total"]
    )
    return 1 if unsafe else 0


if __name__ == "__main__":
    raise SystemExit(main())
