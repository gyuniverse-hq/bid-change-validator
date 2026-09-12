"""이미 받아 둔 초안을 지금 검사기로 다시 채점한다. 모델을 다시 부르지 않는다.

검사기를 고치면 예전 측정치는 옛 기준의 숫자가 된다. 그렇다고 288콜을 다시 돌리면
모델이 매번 다르게 쓰므로 **검사기 변경 때문인지 모델 변동 때문인지 구분되지
않는다.** 초안 원문이 결과 파일에 그대로 있으므로, 같은 초안에 새 검사기만
적용하면 차이는 온전히 검사기 몫이다. 비용도 0 이다.

조판이 결정적이라 브리핑은 골든셋에서 다시 만들어도 그때와 같은 문자열이 나온다.
그래서 항목·라벨·힌트를 재구성할 수 있다.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

from app.ai.quality_eval.business_plan import INPUT_SETS  # noqa: E402
from app.ai.quality_eval.business_plan import check_draft  # noqa: E402
from app.ai.quality_eval.business_plan import derive_content_hints  # noqa: E402
from app.ai.quality_eval.business_plan import derive_user_claims  # noqa: E402
from app.ai.quality_eval.business_plan import parse_qualification_items  # noqa: E402
from app.ai.quality_eval.business_plan import render_briefing  # noqa: E402
from app.ai.quality_eval.business_plan.dataset import load_cases  # noqa: E402


def render_inputs(values: dict[str, str]) -> str:
    """생성기의 BusinessPlanInputs.render() 와 같은 모양. 숫자·주장 대조에 쓴다."""
    labels = {
        "company_overview": "회사 및 보유 역량",
        "proposal_goal": "제안 목표",
        "approach": "수행 방안",
        "differentiators": "차별점",
        "staffing": "투입 조직·인력",
        "schedule": "일정·산출물 계획",
        "additional_notes": "기타 요청사항",
    }
    lines = [
        f"- {labels[key]}: {str(value).strip()}"
        for key, value in values.items()
        if str(value).strip()
    ]
    return "\n".join(lines) or "(추가 입력 없음)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("result_file", type=Path, help="run_business_plan_eval.py 가 남긴 JSON")
    ap.add_argument("--golden-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    payload = json.loads(args.result_file.read_text(encoding="utf-8"))
    baseline = sorted((args.golden_root / "results").glob("*baseline*.json"))[-1]
    cases = {
        case.case_id: case
        for case in load_cases(
            baseline_path=baseline, bundle_path=args.golden_root / "fixture_bundle.json"
        )
    }

    rescored = []
    for record in payload["records"]:
        case = cases[record["case_id"]]
        briefing = render_briefing(
            case.judgments, case.overall_status, case.raw_by_key, case.type_by_key,
            notice_title=case.notice_title,
        )
        items = parse_qualification_items(briefing)
        flagged_labels = {
            label
            for (label, _status), judgment in zip(items, case.judgments)
            if judgment["status"] in ("UNSATISFIED", "UNKNOWN")
        }
        hints = {
            label: derive_content_hints(
                case.value_by_key.get(judgment["requirement_key"]),
                case.raw_by_key.get(judgment["requirement_key"], ""),
            )
            for (label, _status), judgment in zip(items, case.judgments)
        }
        rendered = render_inputs(INPUT_SETS[record["input_set"]])
        report = check_draft(
            record["draft_text"],
            case_id=record["case_id"],
            items=items,
            flagged_labels=flagged_labels,
            supplied_text=f"{briefing}\n{rendered}",
            content_hints=hints,
            user_claims=derive_user_claims(rendered, briefing),
        )
        rescored.append({
            **{k: record[k] for k in ("case_id", "input_set", "run", "draft_chars")},
            "flagged_total": report.flagged_total,
            "omission": report.count("OMISSION"),
            "misstated": report.count("MISSTATED"),
            "contradiction": report.count("CONTRADICTION"),
            "label_deviation": report.count("LABEL_DEVIATION"),
            "sections_ok": report.section_ok,
            "check_markers": report.check_marker_count,
            "claim_sentences": report.claim_sentences,
            "unattributed": report.unattributed,
            "violations": [
                {"kind": v.kind, "label": v.requirement_label, "detail": v.detail}
                for v in report.violations
            ],
            "was": {k: record.get(k) for k in ("omission", "misstated", "contradiction")},
        })

    def total(key: str) -> int:
        return sum(row[key] for row in rescored)

    flagged = sum(row["flagged_total"] for row in rescored)
    summary = {
        "records": len(rescored),
        "flagged_rows_total": flagged,
        "omission_total": total("omission"),
        "misstated_total": total("misstated"),
        "contradiction_total": total("contradiction"),
        "label_deviation_total": total("label_deviation"),
        "claim_sentences_total": total("claim_sentences"),
        "unattributed_total": sum(len(row["unattributed"]) for row in rescored),
        "omission_rate": total("omission") / flagged if flagged else None,
        "sections_ok_rate": sum(1 for r in rescored if r["sections_ok"]) / len(rescored),
        "by_input_set": {
            name: {
                key: sum(r[key] for r in rescored if r["input_set"] == name)
                for key in ("omission", "misstated", "contradiction", "label_deviation",
                            "claim_sentences", "flagged_total")
            }
            for name in dict.fromkeys(r["input_set"] for r in rescored)
        },
        # 같은 케이스를 여러 번 돌렸을 때 흔들리는지. 평균만 보면 "3번 중 1번"과
        # "매번 33%"가 같아 보인다.
        "unsafe_runs_by_case_input": {
            f"{case_id}/{input_set}": [
                r["omission"] + r["misstated"] + r["contradiction"]
                for r in rescored
                if r["case_id"] == case_id and r["input_set"] == input_set
            ]
            for case_id, input_set in dict.fromkeys(
                (r["case_id"], r["input_set"]) for r in rescored
            )
        },
        "changed_from_previous_scoring": sum(
            1
            for r in rescored
            if (r["omission"], r["misstated"], r["contradiction"])
            != (r["was"]["omission"], r["was"]["misstated"], r["was"]["contradiction"])
        ),
    }

    out = args.out or args.result_file.with_name(args.result_file.stem + "_rescored.json")
    out.write_text(
        json.dumps({"source": str(args.result_file), "summary": summary, "records": rescored},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str)[:2600])
    print(f"\n-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
