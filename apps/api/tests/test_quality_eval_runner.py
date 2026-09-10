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
    assert case["analysis_status"] == "PARTIAL"
    assert any(d["code"] == "UNMAPPED_REQUIREMENT" for d in case["analysis"]["diagnostics"])
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
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=ROOT, env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '"model_quality_claim": false' in result.stdout
