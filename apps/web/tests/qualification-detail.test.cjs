/* 실제 상세 TS 모듈을 실행한다. HTTP만 대역이며 React 렌더/실서버 E2E 검증은 아니다. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
function load(file, mocks = {}, fetcher = globalThis.fetch) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, reportDiagnostics: true });
  assert.deepEqual((compiled.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error), []);
  const out = { exports: {} };
  new Function('require', 'module', 'exports', 'fetch', compiled.outputText)(name => {
    if (Object.hasOwn(mocks, name)) return mocks[name];
    throw Error(`Unexpected runtime dependency: ${name}`);
  }, out, out.exports, fetcher);
  return out.exports;
}
const stateModule = load('lib/qualification-state.ts');
const core = load('lib/qualification-detail.ts', { './qualification-state': stateModule });
const viewModule = load('lib/qualification-detail-view.ts', { './qualification-state': stateModule });
const clone = structuredClone;
const day = '2026-09-15';
const created = day + 'T00:00:00Z';
function version(n) {
  return { id: `V${n}`, version_number: n, is_current: n === 2, documents: [{ id: `D${n}`, name: `공고 v${n}` }] };
}
function analysis(n = 2, id = `A${n}`) {
  // 실제 analysis detail에는 summary의 requirement_count/evidence_count가 없다.
  return { id, notice_id: 'N1', notice_version_id: `V${n}`, version_number: n, contract_version: 'ai-analysis-v0.2',
    analysis_kind: 'QUALIFICATION_REQUIREMENTS', status: 'SUCCEEDED', created_at: created,
    target_chunk_ids: [], diagnostics: [], dropped_requirements: [],
    requirements: [{ requirement_key: `R${n}`, notice_version_id: `V${n}`, type: 'INDUSTRY', operator: 'MATCH', value: '1450',
      raw: '업종코드 1450 등록 업체', scope: {}, requirement_role: 'mandatory', required: true, condition_complexity: 'simple', evidence_keys: [`E${n}`] }],
    evidence: [{ evidence_key: `E${n}`, document_id: `D${n}`, notice_version_id: `V${n}`, quote: '업종코드 1450 등록 업체', location: { block_start: 0, block_end: 0 } }],
  };
}
function judgment(n = 2, id = `J${n}`, aid = `A${n}`) {
  return { id, preflight_case_id: 'CASE1', company_id: 'C1', analysis_run_id: aid, notice_version_id: `V${n}`,
    overall_status: 'eligible', rule_version: 'qualification-rules-v0.3', analysis_status: 'SUCCEEDED', reference_date: day, created_at: created,
    profile_snapshot: { company_id: 'C1', industries: [{ code: '1450', name: '급식' }] },
    profile_completeness: { industries: true }, judgments: [{ judgment_key: `JR${n}`, requirement_key: `R${n}`,
      status: 'SATISFIED', basis_type: 'PROFILE', reason_code: 'RULE_MATCH', evidence_held: false, requires_evidence: true,
      requirement_evidence_keys: [`E${n}`], profile_refs: [{ kind: 'industry', field: 'code', value: '1450' }] }],
  };
}
function fixture({ baseline = false } = {}) {
  const f = {
    caseItem: { id: 'CASE1', notice_id: 'N1', company_id: 'C1', current_version_number: 2,
      baseline_version_number: baseline ? 1 : null, notice_title: '테스트 공고', bid_notice_no: 'TEST-1' },
    versions: [version(2), version(1)], analyses: { A2: analysis(2), A1: analysis(1) }, judgments: { J2: judgment(2), J1: judgment(1) },
    state: { contract_version: 'qualification-state-v1', scope: { case_id: 'CASE1', notice_id: 'N1', notice_version_id: 'V2', company_id: 'C1', rule_version: 'qualification-rules-v0.3' },
      lookup_state: 'OK', execution_state: 'SUCCEEDED', coverage_state: 'UNVERIFIED', judgment_state: 'AVAILABLE', freshness_state: 'CHECKS_INCOMPLETE',
      display_state: 'RESULT_AVAILABLE', analysis_run_id: 'A2', selected_judgment_run_id: 'J2', observed_judgment_run_id: 'J2', stored_overall_status: 'eligible',
      stored_reference_date: day, requested_reference_date: null, profile_check: 'MATCH', reference_date_check: 'NOT_REQUESTED', answer_basis_check: 'NOT_APPLICABLE',
      reasons: ['ANALYSIS_COMPLETENESS_UNVERIFIED', 'REFERENCE_DATE_NOT_REQUESTED'], unknown_reasons: [], full_notice_eligibility_asserted: false, state_sha256: 'state-1' },
    questions: [], calls: [],
  };
  const reads = {
    getCase: async id => clone(f.caseItem), getVersions: async id => clone(f.versions), getState: async id => clone(f.state),
    getAnalysis: async id => { f.calls.push(['analysis', id]); return clone(f.analyses[id]); },
    getJudgment: async id => { f.calls.push(['judgment', id]); return clone(f.judgments[id]); },
    listAnalyses: async (id, n) => { f.calls.push(['analyses', n]); return Object.values(f.analyses).filter(x => x.version_number === n).map(x => ({ ...clone(x), requirement_count: x.requirements.length, evidence_count: x.evidence.length })); },
    listJudgments: async id => clone(Object.values(f.judgments)),
    getQuestions: async (id, run) => { f.calls.push(['questions', run]); return clone(f.questions); },
  };
  return { f, reads, load: signal => core.loadQualificationDetail('CASE1', reads, signal) };
}
const invalid = e => e.code === 'QUALIFICATION_DETAIL_INVALID';
const changed = e => e.code === 'QUALIFICATION_DETAIL_CHANGED';

test('current detail uses exact state-selected IDs without latest judgment list selection', async () => {
  const env = fixture(); const d = await env.load();
  assert.equal(d.analysis.id, 'A2'); assert.equal(d.judgment.id, 'J2');
  assert.deepEqual(env.f.calls, [['analysis','A2'],['judgment','J2'],['questions','J2']]);
  assert.equal(d.analysis.requirement_count, undefined);
});
test('detail and catalog share the same presentation policy', async () => {
  const env = fixture(); const d = await env.load();
  assert.equal(viewModule.qualificationDetailView(d).label, stateModule.presentQualificationState(d.state).label);
  assert.equal(viewModule.qualificationDetailView(d).counts.satisfied, 1);
  assert.equal(viewModule.qualificationDetailView(d).warnings.length, 2);
});
for (const [name, change] of [
  ['case', f => f.state.scope.case_id = 'OTHER'], ['company', f => f.state.scope.company_id = 'C2'],
  ['notice', f => f.state.scope.notice_id = 'N2'], ['version', f => f.state.scope.notice_version_id = 'V1'],
  ['unverified profile with selection', f => f.state.profile_check = 'NOT_CHECKED'],
  ['stale with selection', f => f.state.freshness_state = 'STALE'],
  ['blocked with selection', f => f.state.judgment_state = 'BLOCKED'],
]) test(`foreign/inconsistent state: ${name}`, async () => { const e = fixture(); change(e.f); await assert.rejects(e.load()); });
for (const [name, edit] of [
  ['id', a => a.id='foreign'], ['notice', a => a.notice_id='other'], ['version', a => a.notice_version_id='V1'],
  ['version number', a => a.version_number=1], ['contract', a => a.contract_version='other'],
  ['analysis kind', a => a.analysis_kind='other'], ['duplicate requirement', a => a.requirements.push(clone(a.requirements[0]))],
  ['duplicate evidence', a => a.evidence.push(clone(a.evidence[0]))], ['wrong evidence version', a => a.evidence[0].notice_version_id='V1'],
  ['document outside version', a => a.evidence[0].document_id='D1'], ['unresolved evidence', a => a.requirements[0].evidence_keys=['OTHER']],
  ['wrong count if supplied', a => a.requirement_count=50],
]) test(`analysis validation: ${name}`, async () => { const e=fixture(); edit(e.f.analyses.A2); await assert.rejects(e.load(), invalid); });
for (const [name, edit] of [
  ['run id', j=>j.id='other'], ['case', j=>j.preflight_case_id='other'], ['company', j=>j.company_id='C2'],
  ['version', j=>j.notice_version_id='V1'], ['analysis', j=>j.analysis_run_id='A1'], ['rule', j=>j.rule_version='old'],
  ['analysis status', j=>j.analysis_status='PARTIAL'], ['missing row', j=>j.judgments=[]],
  ['duplicate row', j=>j.judgments.push(clone(j.judgments[0]))], ['unknown key', j=>j.judgments[0].requirement_key='OTHER'],
  ['wrong evidence', j=>j.judgments[0].requirement_evidence_keys=['E1']], ['bad status', j=>j.judgments[0].status='OK'],
  ['foreign snapshot', j=>j.profile_snapshot.company_id='C2'], ['stored outcome mismatch', j=>j.overall_status='ineligible'],
  ['date mismatch', j=>j.reference_date='2026-09-14'], ['invalid calendar date', j=>j.reference_date='2026-02-30'],
]) test(`judgment validation: ${name}`, async()=>{const e=fixture();edit(e.f.judgments.J2);await assert.rejects(e.load(),invalid);});
test('older unselected stored judgment never loaded as current', async () => {
  const e=fixture(); Object.assign(e.f.state,{selected_judgment_run_id:null,judgment_state:'REJUDGMENT_REQUIRED',freshness_state:'STALE',display_state:'REJUDGMENT_REQUIRED',profile_check:'CHANGED',reasons:['PROFILE_CHANGED']});
  const d=await e.load();assert.equal(d.judgment,null);assert.equal(viewModule.qualificationDetailView(d).counts,null);
  assert.match(viewModule.qualificationDetailView(d).historical,/이전 저장/);assert(!e.f.calls.some(x=>x[0]==='judgment'));
});
test('latest FAILED analysis never falls back to older successful analysis', async () => {
  const e=fixture();Object.assign(e.f.analyses.A2,{status:'FAILED',requirements:[],evidence:[]});
  Object.assign(e.f.state,{execution_state:'FAILED',selected_judgment_run_id:null,display_state:'ANALYSIS_FAILED',judgment_state:'BLOCKED'});
  const d=await e.load();assert.equal(d.analysis.status,'FAILED');assert.equal(d.judgment,null);assert(!e.f.calls.some(x=>x[1]==='A1'));
});
test('PARTIAL can display selected rows but never successful completeness',async()=>{
  const e=fixture();e.f.analyses.A2.status='PARTIAL';e.f.judgments.J2.analysis_status='PARTIAL';
  Object.assign(e.f.state,{execution_state:'PARTIAL',coverage_state:'INCOMPLETE',display_state:'ANALYSIS_INCOMPLETE',reasons:['ANALYSIS_INCOMPLETE']});
  const d=await e.load();assert.equal(d.judgment.id,'J2');assert.equal(viewModule.qualificationDetailView(d).bucket,'insufficient_data');assert.equal(core.canRevalidateDetail(d),false);
});
test('UNREVIEWED without analysis has unknown counts not zero',async()=>{
  const e=fixture();Object.assign(e.f.state,{analysis_run_id:null,selected_judgment_run_id:null,observed_judgment_run_id:null,stored_overall_status:null,display_state:'UNREVIEWED',execution_state:'NOT_RUN',judgment_state:'NOT_RUN'});
  const d=await e.load();assert.equal(d.analysis,null);assert.equal(d.judgment,null);assert.equal(viewModule.qualificationDetailView(d).counts,null);assert.deepEqual(e.f.calls,[]);
});
test('state read failure is not unreviewed',async()=>{const e=fixture();e.reads.getState=async()=>{throw Error('503');};await assert.rejects(e.load(),/503/);assert.deepEqual(e.f.calls,[]);});
test('second state hash changed discards assembled detail',async()=>{
  const e=fixture();let n=0;e.reads.getState=async()=>({...clone(e.f.state),state_sha256:++n===1?'s1':'s2'});await assert.rejects(e.load(),changed);
});
test('case company changed during read discards detail',async()=>{const e=fixture();let n=0;e.reads.getCase=async()=>({...e.f.caseItem,company_id:++n===1?'C1':'C2'});await assert.rejects(e.load(),changed);});
test('analysis mutated during read does not combine mismatched state',async()=>{const e=fixture();e.f.analyses.A2.status='PARTIAL';await assert.rejects(e.load(),changed);});
test('question failure keeps correct saved judgment and visible warning',async()=>{
  const e=fixture();e.reads.getQuestions=async()=>{throw Error('503');};const d=await e.load();assert.equal(d.judgment.id,'J2');assert.deepEqual(d.questions,[]);assert.match(d.warnings[0],/추가 질문/);
});
test('foreign question never creates an actionable row',async()=>{const e=fixture();e.f.questions=[{requirement_key:'OTHER',askable:true}];const d=await e.load();assert.deepEqual(d.questions,[]);assert.equal(d.warnings.length,1);});
test('baseline stays historical and cannot replace current judgment',async()=>{
  const e=fixture({baseline:true});const d=await e.load();assert.equal(d.judgment.id,'J2');assert.equal(d.baseline.judgment.id,'J1');assert.equal(core.canRevalidateDetail(d),true);
});
test('baseline retrieval failure does not hide current result or enable revalidation',async()=>{
  const e=fixture({baseline:true});e.reads.listAnalyses=async()=>{throw Error('503');};const d=await e.load();assert.equal(d.judgment.id,'J2');assert.equal(core.canRevalidateDetail(d),false);assert.equal(d.warnings.length,1);
});
test('baseline wrong case payload is withheld',async()=>{const e=fixture({baseline:true});e.f.judgments.J1.preflight_case_id='OTHER';const d=await e.load();assert.equal(d.baseline.judgment,null);assert.equal(d.judgment.id,'J2');});
test('same baseline and current version is not a change comparison',async()=>{const e=fixture();e.f.caseItem.baseline_version_number=2;const d=await e.load();assert.equal(d.baseline.version,null);assert.equal(core.canRevalidateDetail(d),false);});
test('baseline current rule selection ignores newer old-rule writes',async()=>{
  const e=fixture({baseline:true});e.f.judgments.J0={...judgment(1,'J0'),rule_version:'old',created_at:'2026-09-16T00:00:00Z'};
  const d=await e.load();assert.equal(d.baseline.judgment.id,'J1');
});
test('baseline changed during reading is not used for revalidation',async()=>{
  const e=fixture({baseline:true});let n=0;e.reads.listAnalyses=async()=>[n++===0?analysis(1):analysis(1,'NEW')];const d=await e.load();assert.equal(d.baseline.analysis,null);assert.equal(d.judgment.id,'J2');
});
test('abort before read performs no reads',async()=>{const e=fixture();const c=new AbortController();c.abort();await assert.rejects(e.load(c.signal),x=>x.code==='DETAIL_ABORTED');});
test('abort after source read stops subsequent judgment loads',async()=>{const e=fixture();const c=new AbortController();const real=e.reads.getAnalysis;e.reads.getAnalysis=async id=>{const result=await real(id);c.abort();return result;};await assert.rejects(e.load(c.signal));assert(!e.f.calls.some(x=>x[0]==='judgment'));});
test('request generation prevents old success and old failure from committing',async()=>{
  const gate=core.createDetailRequestGate();const first=gate.begin(), second=gate.begin();
  assert(first.signal.aborted);assert.equal(first.isCurrent(),false);assert.equal(second.isCurrent(),true);gate.cancel();assert.equal(second.isCurrent(),false);
});
test('no recorded rows means no live profile is invented',()=>{assert.match(viewModule.recordedComparison(null),/선택된 판정 없음/);assert.match(viewModule.recordedComparison({basis_type:'PROFILE'}),/미제공/);});
test('recorded company values and user answers are distinguished',()=>{
  assert.equal(viewModule.recordedComparison(judgment().judgments[0]),'업종코드: 1450');
  assert.match(viewModule.recordedComparison({basis_type:'USER_ANSWER'}),/저장된 사용자 답변/);
});
test('empty diagnostics are not proof that all requirements were found',async()=>{const d=await fixture().load();assert.match(viewModule.qualificationDetailView(d).emptyScope,/발견하지 못한/);});

async function operationEnv({baseline=false}={}) {
  const e=fixture({baseline});const d=await e.load();const calls=[];let loadCount=0;
  const writes={load:async()=>{calls.push(['load',++loadCount]);return e.load();},analyze:async(notice,n)=>{
    calls.push(['analyze',notice,n]);const a=analysis(n,`A${n}NEW`);e.f.analyses[a.id]=a;
    if(n===2){Object.assign(e.f.state,{analysis_run_id:a.id,selected_judgment_run_id:null,display_state:'REJUDGMENT_REQUIRED',state_sha256:'analysis-new'});}
    return clone(a);
  },judge:async(caseId,aid)=>{
    calls.push(['judge',caseId,aid]);const a=e.f.analyses[aid];const j=judgment(a.version_number,`J${a.version_number}NEW`,aid);e.f.judgments[j.id]=j;
    if(a.version_number===2)Object.assign(e.f.state,{analysis_run_id:aid,selected_judgment_run_id:j.id,observed_judgment_run_id:j.id,display_state:'RESULT_AVAILABLE',judgment_state:'AVAILABLE',state_sha256:'judged-new'});
    return clone(j);
  }};
  return {...e,d,writes,calls};
}
test('rejudge uses current analysis and never invokes LLM extraction',async()=>{const e=await operationEnv();const out=await core.executeQualificationReview(e.d,'rejudge',e.writes);assert.equal(out.status,'COMPLETE');assert(!e.calls.some(x=>x[0]==='analyze'));assert.equal(e.calls.filter(x=>x[0]==='judge').length,1);assert.equal(out.detail.judgment.id,'J2NEW');});
test('explicit reanalyze creates new extraction then judgment then authoritative reload',async()=>{const e=await operationEnv();const stages=[];const out=await core.executeQualificationReview(e.d,'reanalyze',e.writes,x=>stages.push(x));assert.equal(out.status,'COMPLETE');assert.deepEqual(stages,['checking','analysis','judgment','refresh']);assert.equal(out.detail.analysis.id,'A2NEW');assert.deepEqual(out.receipts.map(x=>x.kind),['analysis','judgment']);});
test('valid analysis in start mode is reused, not silently regenerated',async()=>{const e=await operationEnv();await core.executeQualificationReview(e.d,'start',e.writes);assert(!e.calls.some(x=>x[0]==='analyze'));});
test('rejudge stops before writes when analysis changed since display',async()=>{const e=await operationEnv();e.f.analyses.NEW=analysis(2,'NEW');e.f.state.analysis_run_id='NEW';e.f.state.selected_judgment_run_id=null;e.f.state.display_state='REJUDGMENT_REQUIRED';await assert.rejects(core.executeQualificationReview(e.d,'rejudge',e.writes),changed);assert(!e.calls.some(x=>['judge','analyze'].includes(x[0])));});
test('case scope change during preflight stops all writes',async()=>{const e=await operationEnv();e.writes.load=async()=>({...e.d,caseItem:{...e.d.caseItem,company_id:'C2'}});await assert.rejects(core.executeQualificationReview(e.d,'reanalyze',e.writes),changed);assert.deepEqual(e.calls,[]);});
test('confirmed save plus failed reload does not retry POST',async()=>{
  const e=await operationEnv();let n=0;const original=e.writes.load;e.writes.load=async()=>{if(n++>0)throw Error('503');return original();};
  const out=await core.executeQualificationReview(e.d,'rejudge',e.writes);assert.equal(out.status,'REFRESH_FAILED');assert.equal(out.detail,null);assert.equal(out.receipts[0].id,'J2NEW');assert.equal(e.calls.filter(x=>x[0]==='judge').length,1);
});
test('POST timeout is uncertain and only reads, never repeats POST',async()=>{
  const e=await operationEnv();let writes=0;e.writes.judge=async()=>{writes++;throw Error('network timeout');};
  const out=await core.executeQualificationReview(e.d,'rejudge',e.writes);assert.equal(out.status,'WRITE_UNCONFIRMED');assert.equal(writes,1);assert.equal(out.detail.judgment.id,'J2');assert.deepEqual(out.receipts,[]);
});
test('analysis acknowledged, later judgment fails: analysis receipt preserved',async()=>{const e=await operationEnv();e.writes.judge=async()=>{throw Error('503');};const out=await core.executeQualificationReview(e.d,'reanalyze',e.writes);assert.equal(out.status,'WRITE_UNCONFIRMED');assert.deepEqual(out.receipts.map(x=>x.kind),['analysis']);assert.equal(out.detail.judgment,null);});
test('newer current result after save is shown explicitly rather than forcing saved response',async()=>{
  const e=await operationEnv();const original=e.writes.judge;e.writes.judge=async(...args)=>{const saved=await original(...args);e.f.judgments.JOTHER=judgment(2,'JOTHER');Object.assign(e.f.state,{selected_judgment_run_id:'JOTHER',observed_judgment_run_id:'JOTHER'});return saved;};
  const out=await core.executeQualificationReview(e.d,'rejudge',e.writes);assert.equal(out.detail.judgment.id,'JOTHER');assert.match(out.message,/달라졌습니다/);
});
test('failed fresh analysis never proceeds to judgment',async()=>{
  const e=await operationEnv();e.writes.analyze=async()=>{const a={...analysis(2,'FAILED'),status:'FAILED',requirements:[],evidence:[]};e.f.analyses.FAILED=a;Object.assign(e.f.state,{analysis_run_id:'FAILED',execution_state:'FAILED',display_state:'ANALYSIS_FAILED',selected_judgment_run_id:null,judgment_state:'BLOCKED'});return clone(a);};
  const out=await core.executeQualificationReview(e.d,'reanalyze',e.writes);assert.equal(out.status,'COMPLETE');assert.equal(out.detail.state.display_state,'ANALYSIS_FAILED');assert(!e.calls.some(x=>x[0]==='judge'));
});
test('abort after analysis ack prevents subsequent judgment write',async()=>{const e=await operationEnv();const c=new AbortController();const original=e.writes.analyze;e.writes.analyze=async(...args)=>{const a=await original(...args);c.abort();return a;};const out=await core.executeQualificationReview(e.d,'reanalyze',e.writes,()=>{},c.signal);assert.equal(out.status,'ABANDONED');assert.equal(out.receipts.length,1);assert(!e.calls.some(x=>x[0]==='judge'));});
test('baseline operation cannot overwrite current judgment display',async()=>{const e=await operationEnv({baseline:true});const out=await core.executeQualificationReview(e.d,'baseline',e.writes);assert.equal(out.detail.judgment.id,'J2');assert(e.calls.some(x=>x[0]==='judge'&&x[2]==='A1'));assert.equal(out.receipts[0].version_number,1);});
test('unsupported operation fails before reads and writes',async()=>{const e=await operationEnv();await assert.rejects(core.executeQualificationReview(e.d,'arbitrary',e.writes),invalid);assert.deepEqual(e.calls,[]);});

function realAdapter(fetcher) {
  const api=load('lib/api.ts',{},fetcher);
  const stateApi=load('lib/qualification-state-api.ts',{'@/lib/api':api,'@/lib/qualification-state':stateModule});
  const qualificationApi=load('lib/qualification-api.ts',{'@/lib/api':api});
  return load('lib/qualification-detail-api.ts',{'@/lib/api':api,'@/lib/qualification-api':qualificationApi,
    '@/lib/qualification-state-api':stateApi,'@/lib/qualification-detail':core});
}
test('real HTTP adapters bind case, state, analysis, judgment, questions with no-store and credentials',async()=>{
  const e=fixture(),requests=[];
  const adapter=realAdapter(async(url,init)=>{
    requests.push([url,init]);const p=new URL(url).pathname;
    const data=p.endsWith('/qualification-state')?e.f.state:p==='/api/v1/preflight-cases/CASE1'?e.f.caseItem:
      p.endsWith('/versions')?e.f.versions:p.endsWith('/qualification-analyses/A2')?e.f.analyses.A2:
      p.endsWith('/qualification-judgment-runs/J2')?e.f.judgments.J2:p.endsWith('/qualification-questions')?[]:null;
    assert.notEqual(data,null,p);return new Response(JSON.stringify(data),{status:200});
  });
  const controller=new AbortController();const d=await adapter.loadCurrentQualificationDetail('CASE1',controller.signal);
  assert.equal(d.judgment.id,'J2');for(const[,init]of requests){assert.equal(init.cache,'no-store');assert.equal(init.credentials,'include');assert.equal(init.signal,controller.signal);assert.equal(init.method,undefined);}
  const question=new URL(requests.find(([url])=>url.includes('qualification-questions'))[0]);assert.equal(question.searchParams.get('source_judgment_run_id'),'J2');
});
for (const status of [401,403,404,409,503]) test(`real HTTP adapter propagates ${status} without fallback`,async()=>{
  const adapter=realAdapter(async()=>new Response(JSON.stringify({error:{code:'TEST_ERROR',message:'오류'}}),{status}));
  await assert.rejects(adapter.loadCurrentQualificationDetail('CASE1'),e=>e.status===status&&e.code==='TEST_ERROR');
});
test('real adapter encodes path identifiers and never infers URLs from IDs',async()=>{
  let url;const adapter=realAdapter(async u=>{url=u;return new Response(JSON.stringify({id:'anything'}));});
  await adapter.detailReadPorts().getCase('A/B?x=1');assert.match(url,/A%2FB%3Fx%3D1$/);
});
test('new TSX files parse and route delegates to state-driven component',()=>{
  for(const file of ['app/qualification/page.tsx','components/product/qualification-review-workspace.tsx','components/product/qualification-state-summary.tsx']) {
    const text=fs.readFileSync(path.join(root,file),'utf8');const parsed=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);assert.deepEqual(parsed.parseDiagnostics,[]);
  }
  const source=fs.readFileSync(path.join(root,'components/product/qualification-review-workspace.tsx'),'utf8');
  assert(!source.includes('loadCaseWorkspace'));assert(!source.includes('setDisplayJudgment(currentJudgment)'));
  assert(source.includes('runCurrentQualificationReview'));assert(source.includes('화면 상태만 다시 조회'));
});


test('same state hash with different actual selection is rejected',async()=>{
  const e=fixture();let n=0;e.reads.getState=async()=>{const state=clone(e.f.state);if(n++>0)state.scope.company_id='C2';return state;};
  await assert.rejects(e.load(),changed);
});
test('state object property order alone is not a basis change',async()=>{
  const e=fixture();let n=0;e.reads.getState=async()=>{const state=clone(e.f.state);return n++===0?state:Object.fromEntries(Object.entries(state).reverse());};
  assert.equal((await e.load()).judgment.id,'J2');
});
test('invalid write response cannot be presented as a confirmed target receipt',async()=>{
  const e=await operationEnv();e.writes.judge=async()=>({...judgment(2,'WRONG'),company_id:'OTHER'});
  const out=await core.executeQualificationReview(e.d,'rejudge',e.writes);assert.equal(out.status,'WRITE_UNCONFIRMED');assert.deepEqual(out.receipts,[]);
});
test('unknown POST outcome plus failed read is never reported as unreviewed',async()=>{
  const e=await operationEnv();let reads=0;e.writes.load=async()=>{if(reads++)throw Error('503');return e.d;};
  e.writes.judge=async()=>{throw Error('timeout');};const out=await core.executeQualificationReview(e.d,'rejudge',e.writes);
  assert.equal(out.status,'WRITE_UNCONFIRMED');assert.equal(out.detail,null);
});
test('cancel during uncertain outcome lookup remains abandoned',async()=>{
  const e=await operationEnv();const c=new AbortController();let reads=0;e.writes.load=async()=>{if(reads++)c.abort();return e.d;};e.writes.judge=async()=>{throw Error('timeout');};
  const out=await core.executeQualificationReview(e.d,'rejudge',e.writes,()=>{},c.signal);assert.equal(out.status,'ABANDONED');
});
