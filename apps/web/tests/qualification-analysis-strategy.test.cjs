/* 실제 전략 선택/HTTP/상세 core를 실행한다. 회사·모델·네트워크는 합성 자료다. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const root = path.resolve(__dirname, '..');
const clone = structuredClone;
function load(file, mocks = {}, fetcher = globalThis.fetch) {
  const source = fs.readFileSync(path.join(root, file), 'utf8');
  const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},reportDiagnostics:true});
  assert.deepEqual((compiled.diagnostics || []).filter(d=>d.category===ts.DiagnosticCategory.Error),[]);
  const out={exports:{}};
  new Function('require','module','exports','fetch',compiled.outputText)(name=>{
    if(Object.hasOwn(mocks,name))return mocks[name];throw Error(`Unexpected dependency: ${name}`);
  },out,out.exports,fetcher);
  return out.exports;
}
const model=load('lib/qualification-state.ts');
const core=load('lib/qualification-detail.ts',{'./qualification-state':model});
const basis=strategy=>({version:'qualification-extraction-basis-v1',strategy,input_sha256:'a'.repeat(64),source_sha256:'b'.repeat(64)});
const caseItem={id:'C',notice_id:'N',company_id:'CO',current_version_number:2,baseline_version_number:null};
const version={id:'V',version_number:2,documents:[{id:'D'}]};
function analysis(strategy,id='A') {
  return {id,notice_id:'N',notice_version_id:'V',version_number:2,status:'SUCCEEDED',
    contract_version:'ai-analysis-v0.2',analysis_kind:'QUALIFICATION_REQUIREMENTS',diagnostics:[],dropped_requirements:[],
    extraction_strategy:strategy,execution_basis:strategy?basis(strategy):undefined,
    requirements:[{requirement_key:'R',notice_version_id:'V',raw:'업종코드 1257 등록',evidence_keys:['E']}],
    evidence:[{evidence_key:'E',document_id:'D',quote:'업종코드 1257 등록'}]};
}
function judgment(a) {
  return {id:'J',preflight_case_id:'C',company_id:'CO',analysis_run_id:a.id,notice_version_id:'V',
    overall_status:'eligible',rule_version:'rule-v',reference_date:'2026-09-15',analysis_status:'SUCCEEDED',
    judgments:[{requirement_key:'R',status:'SATISFIED',basis_type:'PROFILE',requirement_evidence_keys:['E']}]};
}
function scenario(strategy) {
  let current=analysis(strategy);const calls=[];
  const detail=()=>({caseItem,currentVersion:version,analysis:clone(current),judgment:judgment(current),
    baseline:{version:null,analysis:null,judgment:null},state:{execution_state:'SUCCEEDED',display_state:'RESULT_AVAILABLE',
      analysis_run_id:current.id,selected_judgment_run_id:'J',scope:{rule_version:'rule-v'}}});
  const d=detail();
  const writes={load:async()=>detail(),analyze:async(n,v,s)=>{
    calls.push(['analysis',n,v,s]);current=analysis(s,'NEW');return clone(current);
  },judge:async(c,a)=>{calls.push(['judgment',c,a]);return judgment(current);}};
  return {d,writes,calls};
}
for(const stored of [undefined,'legacy'])test(`explicit review does not reuse ${stored??'unrecorded'} analysis`,async()=>{
  const e=scenario(stored);const result=await core.executeQualificationReview(e.d,'start',e.writes,()=>{},undefined,'review_v1');
  assert.equal(result.status,'COMPLETE');assert.equal(e.calls[0][3],'review_v1');
  assert.equal(result.detail.analysis.extraction_strategy,'review_v1');assert.equal(e.calls.length,2);
});
test('same declared review strategy reuses existing result',async()=>{
  const e=scenario('review_v1');const result=await core.executeQualificationReview(e.d,'start',e.writes,()=>{},undefined,'review_v1');
  assert.equal(result.status,'COMPLETE');assert.deepEqual(e.calls,[['judgment','C','A']]);
});
test('rejudge does not reextract when strategy selection differs',async()=>{
  const e=scenario('legacy');const result=await core.executeQualificationReview(e.d,'rejudge',e.writes,()=>{},undefined,'review_v1');
  assert.equal(result.status,'COMPLETE');assert.deepEqual(e.calls,[['judgment','C','A']]);
});
for(const unexpected of [undefined,'legacy'])test(`unexpected returned mode ${unexpected} prevents judgment`,async()=>{
  const e=scenario('legacy');e.writes.analyze=async()=>{e.calls.push(['analysis']);return analysis(unexpected,'NEW');};
  const result=await core.executeQualificationReview(e.d,'reanalyze',e.writes,()=>{},undefined,'review_v1');
  assert.equal(result.status,'WRITE_UNCONFIRMED');assert.deepEqual(e.calls,[['analysis']]);
});
test('graph mode is rejected before any read or write',async()=>{
  const e=scenario();e.writes.load=async()=>assert.fail('read called');
  await assert.rejects(core.executeQualificationReview(e.d,'reanalyze',e.writes,()=>{},undefined,'review_graph_v1'));
  assert.deepEqual(e.calls,[]);
});
for(const edit of [a=>a.extraction_strategy='unknown',a=>a.execution_basis.strategy='legacy',a=>a.execution_basis.input_sha256='bad'])test('invalid execution basis rejected',()=>{
  const a=analysis('review_v1');edit(a);assert.throws(()=>core.validateAnalysis(a,'A','N',version));
});
function apiAdapter(fetcher) {
  const api=load('lib/api.ts',{},fetcher), qa=load('lib/qualification-api.ts',{'@/lib/api':api});
  const stateApi=load('lib/qualification-state-api.ts',{'@/lib/api':api,'@/lib/qualification-state':model});
  return {qa,detail:load('lib/qualification-detail-api.ts',{'@/lib/api':api,'@/lib/qualification-api':qa,
    '@/lib/qualification-state-api':stateApi,'@/lib/qualification-detail':core})};
}
test('real analysis adapter sends explicit JSON strategy, old caller sends no body',async()=>{
  let request;const api=apiAdapter(async(url,init)=>{request=[url,init];return new Response(JSON.stringify(analysis()));});
  await api.qa.runQualificationAnalysis('N',2,'review_v1');assert.deepEqual(JSON.parse(request[1].body),{extraction_strategy:'review_v1'});
  await api.qa.runQualificationAnalysis('N',2);assert.equal(request[1].body,undefined);
});
const options={contract_version:'qualification-analysis-options-v1',default_strategy:'legacy',
  strategies:[{id:'legacy',enabled:true},{id:'review_v1',enabled:true}],graph_product_enabled:false};
test('capability lookup is GET/no-store and validates response',async()=>{
  let request;const api=apiAdapter(async(url,init)=>{request=[url,init];return new Response(JSON.stringify(options));});
  assert.equal((await api.detail.getAnalysisOptions()).strategies[1].enabled,true);
  assert.equal(request[1].method,undefined);assert.equal(request[1].cache,'no-store');
});
for(const edit of [d=>d.graph_product_enabled=true,d=>d.strategies.push(d.strategies[1]),d=>d.default_strategy='review_v1'])test('invalid capabilities not accepted',async()=>{
  const data=clone(options);edit(data);const api=apiAdapter(async()=>new Response(JSON.stringify(data)));
  await assert.rejects(api.detail.getAnalysisOptions());
});
