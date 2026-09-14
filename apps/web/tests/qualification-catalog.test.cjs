/* 실제 TS 모듈을 컴파일해 검사한다. React/브라우저나 HTTP 서버 E2E는 아니다. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const fixture = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures/qualification-catalog.json'), 'utf8'));
function load(file, mocks = {}) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},reportDiagnostics:true});
  assert.deepEqual((compiled.diagnostics || []).filter(d => d.category === ts.DiagnosticCategory.Error), []);
  const out = { exports:{} };
  new Function('require','module','exports',compiled.outputText)((name) => {
    if (Object.hasOwn(mocks,name)) return mocks[name];
    throw Error(`Unexpected dependency: ${name}`);
  },out,out.exports);
  return out.exports;
}
const model = load('lib/qualification-state.ts');
const valid = fixture.items.find(x => x.state?.stored_overall_status === 'eligible' && x.state.display_state === 'RESULT_AVAILABLE').state;
const clone = (value) => structuredClone(value);
const params = {companyId:fixture.company_id};
for (const status of ['eligible','ineligible','insufficient_data']) test(`stored ${status} label`,()=>{
  const view=model.presentQualificationState({...valid,stored_overall_status:status});
  assert.equal(view.bucket,status);assert.match(view.label,/저장 판정/);
});
for (const display of ['REJUDGMENT_REQUIRED','ANALYSIS_FAILED','ANALYSIS_RUNNING','ANALYSIS_INCOMPLETE','DATA_INVALID','LOAD_FAILED','PROFILE_REQUIRED','JUDGMENT_REQUIRED','NEW_STATE']) test(`${display} never displays old eligible as current`,()=>{
  const state={...valid,display_state:display,selected_judgment_run_id:null};
  assert.equal(model.presentQualificationState(state).bucket,'insufficient_data');
  assert.match(model.historicalLabel(state),/이전 저장 결과/);
});
test('legacy completeness and missing date remain visible warnings',()=>{
  const view=model.presentQualificationState(valid);
  assert(view.warnings.some(x=>x.includes('빠짐없이')));assert(view.warnings.some(x=>x.includes('기준일')));
});
test('lookup failure overrides stored available result',()=>{
  const view=model.presentQualificationState({...valid,lookup_state:'FAILED'});
  assert.equal(view.bucket,'insufficient_data');assert.match(view.label,/조회 실패/);
});
test('explicit unreviewed only',()=>{
  const state={...valid,display_state:'UNREVIEWED',selected_judgment_run_id:null,observed_judgment_run_id:null,stored_overall_status:null};
  assert.equal(model.presentQualificationState(state).bucket,'unreviewed');assert.equal(model.historicalLabel(state),null);
});
test('actual backend fixture parses with scope and counters',()=>{
  const parsed=model.parseNoticeCatalog(fixture,params);
  assert.equal(parsed.total,5);assert.equal(parsed.status_counts.eligible,2);assert.equal(parsed.business_counts.CONSTRUCTION,1);
});
for(const [name,edit] of [
  ['company',d=>d.company_id='foreign'],['query',d=>d.query='wrong'],['offset',d=>d.offset=20],
  ['counts',d=>d.status_counts.eligible++],['business count',d=>d.business_counts.SERVICE++],
  ['duplicate',d=>d.items[1]=d.items[0]],['missing state',d=>d.items[0].state=null],
  ['wrong scope',d=>d.items[0].state.scope.notice_id='foreign'],['wrong bucket',d=>d.items[0].status_bucket=d.items[0].status_bucket==='ineligible'?'eligible':'ineligible'],
  ['unrecognized version',d=>d.contract_version='unknown']
]) test(`bad catalog ${name} rejected`,()=>{const d=clone(fixture);edit(d);assert.throws(()=>model.parseNoticeCatalog(d,params));});
for(const [name,edit] of [
  ['scope',d=>d.scope.case_id='wrong'],['selected id',d=>d.selected_judgment_run_id='wrong'],
  ['missing field',d=>delete d.coverage_state],['missing reasons',d=>delete d.reasons],
  ['unexpected assertion',d=>d.full_notice_eligibility_asserted=true],['bad overall',d=>d.stored_overall_status='ok']
]) test(`bad state ${name} rejected`,()=>{const d=clone(valid);edit(d);assert.throws(()=>model.parseQualificationState(d,valid.scope.case_id));});
test('search parameters go to backend, not local page filtering',()=>{
  const q=new URLSearchParams(model.catalogSearch({companyId:'C',query:'  100% 공고  ',businessType:'CONSTRUCTION',status:'ineligible',offset:100,limit:20}));
  assert.equal(q.get('q'),'100% 공고');assert.equal(q.get('business_type'),'CONSTRUCTION');assert.equal(q.get('status'),'ineligible');assert.equal(q.get('offset'),'100');
});
class ApiError extends Error {constructor(message,status,code){super(message);this.status=status;this.code=code;}}
test('catalog API sends credentials path through existing apiFetch',async()=>{
  let observed;
  const api=load('lib/qualification-state-api.ts',{'@/lib/api':{ApiError,apiFetch:async(...args)=>{observed=args;return {ok:true,json:async()=>fixture};}},'@/lib/qualification-state':model});
  await api.getNoticeCatalog(params);
  assert.match(observed[0],/^\/api\/v1\/qualification-notice-catalog\?/);assert.equal(observed[1].cache,'no-store');
});
for(const status of [401,403,404,409,503]) test(`HTTP ${status} not fallback to unreviewed`,async()=>{
  const api=load('lib/qualification-state-api.ts',{'@/lib/api':{ApiError,apiFetch:async()=>({ok:false,status,json:async()=>({error:{message:'응답 오류',code:'FAILED'}})})},'@/lib/qualification-state':model});
  await assert.rejects(api.getNoticeCatalog(params),e=>e.status===status);
});
test('network failure is propagated',async()=>{
  const api=load('lib/qualification-state-api.ts',{'@/lib/api':{ApiError,apiFetch:async()=>{throw new ApiError('연결 실패',0,'NETWORK_ERROR');}},'@/lib/qualification-state':model});
  await assert.rejects(api.getNoticeCatalog(params),e=>e.code==='NETWORK_ERROR');
});
const target={noticeId:'N',bidNoticeNo:'R1',versionNumber:2,companyId:'C'};
const caseItem={id:'CASE',notice_id:'N',company_id:'C',current_version_number:2};
function targetApi(overrides={}) {
  const calls={writes:[],reads:[]};
  const deps={getNoticeVersions:async()=>[{id:'V2',version_number:2,is_current:true},{id:'V1',version_number:1,is_current:false}],getPreflightCase:async()=>caseItem,
    apiFetch:async(...args)=>{calls.reads.push(args);return {ok:true,json:async()=>({total:0,items:[]})};},...overrides};
  const module=load('lib/notice-review-target.ts',{'@/lib/api':deps,'@/lib/qualification-api':{createPreflightCaseWithCompany:async(input)=>{calls.writes.push(input);return {id:'NEW'};}}});
  return {...module,calls};
}
test('existing selected case reused without write',async()=>{const a=targetApi();assert.equal(await a.openReviewTarget({...target,caseId:'CASE'}),'CASE');assert.equal(a.calls.writes.length,0);});
test('matching searches notice and company before create',async()=>{const a=targetApi();assert.equal(await a.openReviewTarget(target),'NEW');const p=new URL('http://test'+a.calls.reads[0][0]);assert.equal(p.searchParams.get('notice_id'),'N');assert.equal(p.searchParams.get('company_id'),'C');assert.equal(a.calls.writes[0].baseline_version_number,1);});
test('current version changed never writes a different version',async()=>{const a=targetApi({getNoticeVersions:async()=>[{is_current:true,version_number:3}]});await assert.rejects(a.openReviewTarget(target));assert.equal(a.calls.writes.length,0);});
test('no current version does not fall back to first version',async()=>{const a=targetApi({getNoticeVersions:async()=>[{is_current:false,version_number:2}]});await assert.rejects(a.openReviewTarget(target));assert.equal(a.calls.writes.length,0);});
test('wrong selected company blocks navigation',async()=>{const a=targetApi({getPreflightCase:async()=>({...caseItem,company_id:'other'})});await assert.rejects(a.openReviewTarget({...target,caseId:'CASE'}));assert.equal(a.calls.writes.length,0);});
test('query failure never creates duplicate case',async()=>{const a=targetApi({apiFetch:async()=>({ok:false})});await assert.rejects(a.openReviewTarget(target));assert.equal(a.calls.writes.length,0);});
test('current case outside first page found',async()=>{
  const reads=[];const a=targetApi({apiFetch:async(url)=>{reads.push(url);return {ok:true,json:async()=>reads.length===1?{total:101,items:Array.from({length:100},()=>({...caseItem,current_version_number:1}))}:{total:101,items:[caseItem]}};}});
  assert.equal(await a.openReviewTarget(target),'CASE');assert.match(reads[1],/offset=100/);assert.equal(a.calls.writes.length,0);
});
test('incomplete case page is error not empty data',async()=>{const a=targetApi({apiFetch:async()=>({ok:true,json:async()=>({total:100,items:[]})})});await assert.rejects(a.openReviewTarget(target));assert.equal(a.calls.writes.length,0);});
test('TSX changed files parse successfully',()=>{
  for(const file of ['app/notices/page.tsx','components/product/notice-review-catalog.tsx','components/product/cached-notice-matches.tsx']){
    const source=fs.readFileSync(path.join(root,file),'utf8');const parsed=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
    assert.deepEqual(parsed.parseDiagnostics,[],file);
  }
});
