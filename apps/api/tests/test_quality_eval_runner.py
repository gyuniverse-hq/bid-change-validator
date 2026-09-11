import os
from pathlib import Path
import subprocess
import sys

from apps.api.app.scripts.quality_eval_report import build_report

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "samples/golden/qualification-quality-v0.1"


def test_selection_only_does_not_claim_extraction():
    report = build_report(DATA)
    assert report["model_quality_claim"] is False
    case = report["cases"][0]
    assert case["analysis"] is None
    assert case["metrics"]["canonical_match"]["value"] is None


def test_synthetic_pipeline_preserves_unmapped_evidence():
    report = build_report(DATA, synthetic_extraction=True)
    assert report["mode"] == "synthetic-harness-check"
    case = report["cases"][0]
    assert case["metrics"]["canonical_match"]["value"] == 1
    assert case["metrics"]["evidence_preserved"]["value"] == 1
    # UNMAPPED_REQUIREMENT 는 "공고에서 확인했으나 닫힌 유형으로 판정할 성질이
    # 아님" 이라는 정상 결과다. 파이프라인이 요건을 잃은 것과는 뜻이 다르므로
    # 분석 품질 저하(PARTIAL)로 보지 않는다 — 근거는 남기고 상태는 SUCCEEDED.
    assert case["analysis_status"] == "SUCCEEDED"
    fact = next(
        d for d in case["analysis"]["diagnostics"] if d["code"] == "UNMAPPED_REQUIREMENT"
    )
    assert fact["kind"] == "NOTICE_FACT"
    assert fact["evidence_keys"], "판정 대상이 아니어도 근거는 보존되어야 한다"
    assert case["extractor_calls"] == 1


def test_cli_runs_without_db_demo_or_network_modules():
    code = '''
import runpy, sys
def deny_network(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("offline evaluation attempted network access")
sys.addaudithook(deny_network)
sys.argv = ["quality_eval_report", "--dataset", "samples/golden/qualification-quality-v0.1", "--synthetic-extraction"]
runpy.run_module("apps.api.app.scripts.quality_eval_report", run_name="__main__")
assert not any(".demo" in name or "sqlalchemy" in name or "fastapi" in name for name in sys.modules)
'''
    # 리포트에 한글 진단 문구가 들어간다. Windows 기본 인코딩(cp949)으로 읽으면
    # UnicodeDecodeError 로 캡처 자체가 실패해 stdout 이 None 이 된다.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    assert '"model_quality_claim": false' in result.stdout
