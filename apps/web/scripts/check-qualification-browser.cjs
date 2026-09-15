/* 실제 React 페이지/Chromium을 실행하는 합성 HTTP 통합 검사.
 * 원문·회사·판정 응답은 합성이다. 실제 남원글로컬 LLM/운영 DB 검증으로 집계하지 않는다.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const origin = process.env.QUALIFICATION_UI_URL || 'http://localhost:3000';
const out = process.env.QUALIFICATION_SCREENSHOT_DIR || '/tmp/qualification-browser';
fs.mkdirSync(out, { recursive: true });
const day = '2026-09-15', now = day + 'T00:00:00Z';
const title = '[합성 검증] 공고 목록과 상세 상태 연결';
const cid = 'qa-case', nid = 'qa-notice', coid = 'qa-company';
const company = { id: coid, name: '합성 검증 회사', business_registration_number: null,
  region_code: null, region_name: '테스트지역', company_size: 'SMALL', industries: [{code:'1257',name:'합성 업종',verified:false}],
  staff: null, performances: [], certifications: [], created_at: now, updated_at: now };
const caseItem = { id:cid, company_id:coid, notice_id:nid, bid_notice_no:'QA-STATE-001', notice_title:title,
  title:'합성 상태 검증', status:'DRAFT', baseline_version_number:null, current_version_number:2,
  documents:[], created_at:now, updated_at:now };
const version = { id:'qa-v2', version_number:2, bid_notice_order:'001', is_current:true,
  documents:[{id:'qa-doc',name:'합성 근거.txt',viewer_type:'TEXT',extraction_status:'SUCCEEDED',extracted_char_count:22}],
  estimated_price:null, allocated_budget:null, contract_method:null, bid_closed_at:null, opened_at:null };
const requirement = { requirement_key:'qa-r', notice_version_id:version.id, type:'INDUSTRY', operator:'MATCH', value:'1257',
  raw:'업종코드 1257을 등록한 업체', scope:{}, period_months:null, unit:null, requirement_group_key:null,
  group_operator:'ALL_OF', requirement_role:'mandatory',required:true,condition_complexity:'simple',evidence_keys:['qa-e'] };
const analysis = {id:'qa-a', notice_id:nid, notice_version_id:version.id, version_number:2,
  contract_version:'ai-analysis-v0.2',analysis_kind:'QUALIFICATION_REQUIREMENTS',status:'SUCCEEDED',created_at:now,
  target_chunk_ids:[],diagnostics:[],dropped_requirements:[],requirements:[requirement],
  evidence:[{evidence_key:'qa-e',document_id:'qa-doc',notice_version_id:version.id,quote:requirement.raw,location:{block_start:0,block_end:0}}]};
let judgmentId = 'qa-j', stale = false, readError = false, failAfterWrite = false, reviewEnabled = false;
let judgmentPosts = 0, analysisPosts = 0;
const catalogCalls = [], unexpected = [], pageErrors = [], checks = [];
function judgment() {
  return {id:judgmentId,preflight_case_id:cid,company_id:coid,analysis_run_id:analysis.id,notice_version_id:version.id,
    overall_status:'eligible',rule_version:'qualification-rules-v0.3',analysis_status:'SUCCEEDED',reference_date:day,created_at:now,
    profile_snapshot:{company_id:coid,industries:company.industries},profile_completeness:{industries:true},
    judgments:[{judgment_key:'qa-jr',requirement_key:'qa-r',status:'SATISFIED',basis_type:'PROFILE',reason_code:'RULE_MATCH',
      evidence_held:false,requires_evidence:true,requirement_evidence_keys:['qa-e'],profile_refs:[{kind:'industry',field:'code',value:'1257'}]}]};
}
function state() {
  return {contract_version:'qualification-state-v1',scope:{case_id:cid,notice_id:nid,notice_version_id:version.id,company_id:coid,rule_version:'qualification-rules-v0.3'},
    lookup_state:'OK',execution_state:'SUCCEEDED',coverage_state:'UNVERIFIED',judgment_state:stale?'REJUDGMENT_REQUIRED':'AVAILABLE',
    freshness_state:stale?'STALE':'CHECKS_INCOMPLETE',display_state:stale?'REJUDGMENT_REQUIRED':'RESULT_AVAILABLE',
    analysis_run_id:analysis.id,selected_judgment_run_id:stale?null:judgmentId,observed_judgment_run_id:judgmentId,
    stored_overall_status:'eligible',stored_reference_date:day,requested_reference_date:null,profile_check:stale?'CHANGED':'MATCH',
    reference_date_check:'NOT_REQUESTED',answer_basis_check:'NOT_APPLICABLE',
    reasons:stale?['PROFILE_CHANGED']:['ANALYSIS_COMPLETENESS_UNVERIFIED','REFERENCE_DATE_NOT_REQUESTED'],unknown_reasons:[],
    full_notice_eligibility_asserted:false,state_sha256:`qa-${judgmentId}-${stale}`};
}
function catalog(url) {
  catalogCalls.push(url.toString());
  const p=url.searchParams, q=p.get('q')||'', type=p.get('business_type'), status=p.get('status'), limit=Number(p.get('limit')||20), offset=Number(p.get('offset')||0);
  let rows=[{id:nid,bid_notice_no:'QA-STATE-001',title,business_type:'SERVICE',notice_kind:null,institution_name:'합성 기관',current_version:2,notice_version_id:version.id,
    case_id:cid,state:state(),status_bucket:stale?'insufficient_data':'eligible',review_basis:stale?'NO_CURRENT_JUDGMENT':'STORED_JUDGMENT'},
    {id:'qa-construction',bid_notice_no:'QA-STATE-002',title:'[합성 검증] 공사 필터',business_type:'CONSTRUCTION',notice_kind:null,institution_name:'합성 기관',current_version:1,
      notice_version_id:'qa-cv1',case_id:null,state:null,status_bucket:'unreviewed',review_basis:'NO_CURRENT_JUDGMENT'}];
  rows=rows.filter(x=>!q||x.title.includes(q)||x.bid_notice_no.includes(q));
  const business_counts={};for(const item of rows)business_counts[item.business_type]=(business_counts[item.business_type]||0)+1;
  const query_total=rows.length;rows=rows.filter(x=>!type||x.business_type===type);
  const scope_total=rows.length,status_counts={eligible:0,ineligible:0,insufficient_data:0,unreviewed:0};for(const row of rows)status_counts[row.status_bucket]++;
  rows=rows.filter(x=>!status||x.status_bucket===status);
  return {contract_version:'qualification-catalog-v1',company_id:coid,query:q,business_type:type,status_filter:status,
    query_total,scope_total,total:rows.length,business_counts,status_counts,limit,offset,items:rows.slice(offset,offset+limit),scope_sha256:'qa-scope',full_notice_eligibility_asserted:false};
}
(async()=>{
  const browser=await chromium.launch({headless:true});let page;
  try {
    page=await browser.newPage({viewport:{width:1440,height:1000}});
    page.setDefaultTimeout(20000);
    page.on('pageerror',error=>pageErrors.push(error.message));
    await page.route('**/api/v1/**',async route=>{
      const req=route.request(),url=new URL(req.url()),p=url.pathname;
      const headers={'access-control-allow-origin':origin,'access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type','access-control-allow-methods':'GET,POST,OPTIONS'};
      const reply=(body,status=200)=>route.fulfill({status,contentType:'application/json',headers,body:JSON.stringify(body)});
      if(req.method()==='OPTIONS')return route.fulfill({status:204,headers});
      if(p==='/api/v1/auth/me')return reply(null);
      if(p==='/api/v1/companies')return reply([company]);
      if(p==='/api/v1/qualification-analysis-options')return reply({contract_version:'qualification-analysis-options-v1',default_strategy:'legacy',strategies:[{id:'legacy',enabled:true},{id:'review_v1',enabled:reviewEnabled}],graph_product_enabled:false});
      if(p.endsWith('/notice-matches'))return reply({company_id:coid,analyzed_notice_count:0,returned_count:0,items:[],note:'합성 검증'});
      if(p==='/api/v1/qualification-notice-catalog')return reply(catalog(url));
      if(p===`/api/v1/preflight-cases/${cid}`)return reply(caseItem);
      if(p==='/api/v1/preflight-cases')return reply({items:[caseItem],total:1,limit:100,offset:0});
      if(p.endsWith('/qualification-state'))return readError?reply({error:{code:'QUALIFICATION_STATE_UNAVAILABLE',message:'합성 상태 조회 실패'}},503):reply(state());
      if(p===`/api/v1/notices/${nid}/versions`)return reply([version]);
      if(p===`/api/v1/notices/${nid}`)return reply({id:nid,title,bid_notice_no:'QA-STATE-001',business_type:'SERVICE',announcing_institution_name:'합성 기관',latest:version});
      if(p===`/api/v1/qualification-analyses/${analysis.id}`)return reply(analysis);
      if(p.startsWith('/api/v1/qualification-judgment-runs/'))return reply(judgment());
      if(p.endsWith('/qualification-questions'))return reply([]);
      if(p.endsWith('/qualification-judgments')&&req.method()==='POST'){
        assert.equal(req.postDataJSON().analysis_run_id,analysis.id);judgmentPosts++;judgmentId=`qa-j-${judgmentPosts}`;
        stale=false;if(failAfterWrite)readError=true;return reply(judgment());
      }
      if(p.endsWith('/qualification-analysis')&&req.method()==='POST'){
        assert.equal(req.postDataJSON().extraction_strategy,'review_v1');analysisPosts++;
        analysis.id='qa-a-review';analysis.extraction_strategy='review_v1';
        analysis.execution_basis={version:'qualification-extraction-basis-v1',strategy:'review_v1',input_sha256:'a'.repeat(64),source_sha256:'b'.repeat(64)};
        return reply(analysis);
      }
      unexpected.push(`${req.method()} ${p}`);return reply({error:{code:'UNEXPECTED_TEST_ROUTE',message:p}},404);
    });
    await page.goto(`${origin}/notices`);
    await page.getByText(title,{exact:true}).waitFor();
    const region=page.getByRole('region',{name:'검색된 공고의 저장 검토 상태'});
    await region.getByRole('button',{name:/^공사 /}).click();
    await page.getByText('[합성 검증] 공사 필터',{exact:true}).waitFor();
    await page.waitForFunction(()=>!document.body.innerText.includes('공고와 저장 판정 상태를 조회하고 있습니다.'));
    assert(catalogCalls.some(x=>new URL(x).searchParams.get('business_type')==='CONSTRUCTION'));
    checks.push('catalog server-side construction filter');
    await page.screenshot({path:path.join(out,'01-catalog.png'),fullPage:true});
    await page.goto(`${origin}/qualification?caseId=${cid}`);
    await page.locator('#qualification-conclusion').filter({hasText:'저장 판정: 응찰 가능'}).waitFor();
    await page.getByRole('button',{name:'근거 보기',exact:true}).click();
    await page.getByRole('region',{name:'선택한 원문 근거'}).getByText(requirement.raw,{exact:false}).waitFor();
    assert.equal(judgmentPosts,0);assert.equal(analysisPosts,0);
    checks.push('detail selected judgment and source render with no writes');
    await page.screenshot({path:path.join(out,'02-detail.png'),fullPage:true});
    await page.getByRole('button',{name:'현재 분석으로 회사 재판정',exact:true}).click();
    await page.getByText('판정 저장 후 상태와 근거를 다시 조회했습니다. 분석 완전성과 판정 기준은 아래에서 별도로 확인해 주세요.',{exact:true}).waitFor();
    assert.equal(judgmentPosts,1);assert.equal(analysisPosts,0);checks.push('rejudge does not reextract');
    stale=true;await page.getByRole('button',{name:'상태 다시 조회',exact:true}).click();
    await page.locator('#qualification-conclusion').filter({hasText:'재판정 필요'}).waitFor();
    assert.equal(await page.locator('section[aria-labelledby="qualification-conclusion"] strong').filter({hasText:'—'}).count(),3);
    checks.push('changed profile shows stale and unknown counts, not zero/current eligible');
    await page.screenshot({path:path.join(out,'03-stale.png'),fullPage:true});
    stale=false;await page.getByRole('button',{name:'상태 다시 조회',exact:true}).click();
    await page.locator('#qualification-conclusion').filter({hasText:'저장 판정: 응찰 가능'}).waitFor();
    failAfterWrite=true;await page.getByRole('button',{name:'현재 분석으로 회사 재판정',exact:true}).click();
    await page.getByText('판정 저장은 확인했지만 후속 상태 조회에 실패했습니다. 다시 실행하지 말고 화면 상태만 다시 조회해 주세요.',{exact:true}).waitFor();
    assert.equal(judgmentPosts,2);assert.equal(analysisPosts,0);
    readError=false;failAfterWrite=false;await page.getByRole('button',{name:'화면 상태만 다시 조회',exact:true}).click();
    await page.locator('#qualification-conclusion').filter({hasText:'저장 판정: 응찰 가능'}).waitFor();
    assert.equal(judgmentPosts,2);checks.push('saved-then-read-failed recovers with GET only');
    readError=true;await page.getByRole('button',{name:'상태 다시 조회',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'합성 상태 조회 실패'}).waitFor();
    assert.equal(await page.locator('#qualification-conclusion').count(),0);
    checks.push('503 never becomes unreviewed/zero');
    readError=false;await page.getByRole('button',{name:'화면 상태만 다시 조회',exact:true}).click();
    await page.locator('#qualification-conclusion').waitFor();
    assert.equal(await page.locator('#qualification-extraction-strategy option[value="review_v1"]').isDisabled(),true);
    reviewEnabled=true;
    await page.reload();
    await page.waitForFunction(()=>{const option=document.querySelector('#qualification-extraction-strategy option[value="review_v1"]');return option && !option.disabled;});
    await page.getByLabel('새 분석에 사용할 방식',{exact:true}).selectOption('review_v1');
    await page.getByRole('button',{name:'현재 차수 다시 분석',exact:true}).click();
    await page.getByText('판정 저장 후 상태와 근거를 다시 조회했습니다. 분석 완전성과 판정 기준은 아래에서 별도로 확인해 주세요.',{exact:true}).waitFor();
    await page.getByText(/저장된 분석 방식: review_v1/).waitFor();
    assert.equal(analysisPosts,1);assert.equal(judgmentPosts,3);
    checks.push('explicit review_v1 selection posts selected strategy and displays persisted basis');
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'04-mobile.png'),fullPage:true});
    assert.equal(pageErrors.length,0,pageErrors.join('\n'));assert.deepEqual(unexpected,[]);
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({kind:'SYNTHETIC_HTTP_BROWSER',checks,judgmentPosts,analysisPosts,pageErrors,unexpected,live_model:false,production_db:false},null,2));
    console.log(JSON.stringify({kind:'SYNTHETIC_HTTP_BROWSER',passed:checks.length,judgmentPosts,analysisPosts}));
  } catch(error) {
    if(page){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(out,'failure.html'),await page.content().catch(()=>''));}
    fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(error),checks,pageErrors,unexpected},null,2));throw error;
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
