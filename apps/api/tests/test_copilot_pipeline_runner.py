"""Readiness must not reuse stale product output or a model's own PASS."""
import json
from scripts.run_copilot_pipeline import reviewed_job,sha


def test_model_pass_without_independent_review_is_not_a_gate_pass(tmp_path):
    current={'apps/api/app/copilot/orchestration.py':'new'}
    report=tmp_path/'report.json'
    report.write_text(json.dumps({'runtime':{'source':{'files':current}},'transport':'PASS','steps':[{'task_status':'PASS'}]}),encoding='utf-8')
    assert reviewed_job(report,current)=='NEEDS_SOURCE_REVIEW'
    review=tmp_path/'review.json'
    review.write_text(json.dumps({'report_sha256':sha(report),'result':'PASS','reviewer':'independent source review','source_checks':['claim compared with fixed source']}),encoding='utf-8')
    assert reviewed_job(report,current)=='PASS'
    report.write_text(report.read_text()+'\n',encoding='utf-8')
    assert reviewed_job(report,current)=='STALE_REVIEW'


def test_product_change_invalidates_previously_reviewed_job(tmp_path):
    report=tmp_path/'report.json'
    report.write_text(json.dumps({'runtime':{'source':{'files':{'apps/api/app/copilot/orchestration.py':'old'}}},'transport':'PASS'}),encoding='utf-8')
    assert reviewed_job(report,{'apps/api/app/copilot/orchestration.py':'new'})=='STALE_PRODUCT'


def test_ui_receipt_never_certifies_a_changed_backend(tmp_path,monkeypatch):
    import scripts.run_copilot_pipeline as runner
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    artifact=tmp_path/'screen.png';artifact.write_bytes(b'captured display')
    current={'apps/api/app/x.py':'same','apps/web/page.tsx':'new'}
    proof={'status':'PASS','product':current,'covered_paths':['apps/web/page.tsx'],
           'checks':[{'status':'PASS'}],'artifacts':[{'path':'screen.png','sha256':sha(artifact)}]}
    (tmp_path/'ui-recheck.json').write_text(json.dumps(proof))
    old={'source':{'files':{'apps/api/app/x.py':'same','apps/web/page.tsx':'old'}}}
    assert runner.verified_basis(old,current,tmp_path)
    assert not runner.verified_basis(old,{**current,'apps/api/app/x.py':'changed'},tmp_path)
    artifact.write_bytes(b'changed')
    assert not runner.verified_basis(old,current,tmp_path)
