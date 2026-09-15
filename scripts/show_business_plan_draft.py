"""측정 결과를 터미널에서 읽는다. 결과 JSON 이 수 MB 라 그냥 열면 못 본다.

    # 어떤 초안들이 있나
    python scripts/show_business_plan_draft.py <결과.json> --list

    # 위반이 잡힌 것만
    python scripts/show_business_plan_draft.py <결과.json> --violations

    # 초안 한 편 통독 (판정 결과와 나란히)
    python scripts/show_business_plan_draft.py <결과.json> --case J25 --input BOASTFUL \\
        --golden-root "<골든셋 폴더>"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result_file", type=Path)
    ap.add_argument("--list", action="store_true", help="한 줄 요약으로 전부 나열")
    ap.add_argument("--violations", action="store_true", help="위반이 잡힌 것만")
    ap.add_argument("--case", default=None)
    ap.add_argument("--input", dest="input_set", default=None)
    ap.add_argument("--run", type=int, default=None)
    ap.add_argument("--golden-root", type=Path, default=None,
                    help="주면 모델이 본 판정 결과를 초안 앞에 함께 보여준다")
    args = ap.parse_args()

    payload = json.loads(args.result_file.read_text(encoding="utf-8"))
    records = payload["records"]

    if args.violations:
        shown = 0
        for record in records:
            bad = [v for v in record.get("violations", []) if v["kind"] != "SECTIONS"]
            if not bad:
                continue
            shown += 1
            print(f"\n[{record['case_id']}/{record['input_set']}/run{record['run']}]")
            for violation in bad:
                print(f"  {violation['kind']:<16}{violation.get('label') or ''}")
                print(f"    {violation['detail']}")
        print(f"\n위반이 잡힌 초안 {shown}편 / 전체 {len(records)}편")
        return 0

    selected = [
        r for r in records
        if (args.case is None or r["case_id"] == args.case)
        and (args.input_set is None or r["input_set"] == args.input_set)
        and (args.run is None or r["run"] == args.run)
    ]

    if args.list or not (args.case or args.input_set):
        print(f"{'케이스':<8}{'입력':<10}{'회차':<5}{'글자':>6}  위반")
        for record in selected:
            unsafe = sum(record.get(k, 0) for k in ("omission", "misstated", "contradiction"))
            marks = record.get("check_markers", "-")
            print(f"{record['case_id']:<8}{record['input_set']:<10}"
                  f"{record['run']:<5}{record.get('draft_chars', 0):>6}  "
                  f"{'없음' if unsafe == 0 else f'{unsafe}건'} (확인표시 {marks})")
        print(f"\n{len(selected)}편")
        return 0

    if not selected:
        print("해당하는 초안이 없습니다.")
        return 1

    record = selected[0]
    if args.golden_root:
        from app.ai.quality_eval.business_plan import render_briefing
        from app.ai.quality_eval.business_plan.dataset import load_cases

        baseline = sorted((args.golden_root / "results").glob("*baseline*.json"))[-1]
        cases = {
            c.case_id: c
            for c in load_cases(
                baseline_path=baseline,
                bundle_path=args.golden_root / "fixture_bundle.json",
            )
        }
        case = cases[record["case_id"]]
        print("=" * 70)
        print("모델이 본 판정 결과")
        print("=" * 70)
        print(render_briefing(case.judgments, case.overall_status, case.raw_by_key,
                              case.type_by_key, notice_title=case.notice_title))

    print("=" * 70)
    print(f"초안  {record['case_id']} / {record['input_set']} / run{record['run']}"
          f"  ({record.get('draft_chars', 0)}자)")
    print("=" * 70)
    print(record.get("draft_text") or "(이 파일에는 초안 원문이 없습니다 — 재채점 파일이 아니라 "
                                      "run_business_plan_eval.py 가 낸 원본을 여세요)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
