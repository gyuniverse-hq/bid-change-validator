/* 실제 React/Chromium 그래프 비교 화면. HTTP 자료는 합성이며 실공고 정확도 검증이 아니다. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const origin=process.env.QUALIFICATION_UI_URL||'http://localhost:3000';
const out=path.join(process.env.QUALIFICATION_SCREENSHOT_DIR||'/tmp/qualification-browser','graph');
const caseId='graph-test-case';
fs.mkdirSync(out,{recursive:true});
let fail=false,posts=0;const unexpected=[],errors=[],checks=[];
const options={contract_version:'qualification-graph-options-v1',enabled:false,copilot_connected:false};
const runs={case_id:caseId,baseline_version_id:'v1',current_version_id:'v2',limit:100,more_may_exist:false,
  items:[['before','v1'],['after','v2']].map(([id,vid])=>({id,notice_id:'N',notice_version_id:vid,contract_version:'qualification-document-graph-v1',status:'PARTIAL',snapshot_sha256:id,created_at:'2026-09-15T00:00:00Z',relation_status:'UNRESOLVED',clause_count:1}))};
const side={candidate_id:'c',document_id:'d',block_index:0,quote:'[합성] 업종코드 1257 등록 업체',meaning:null};
const result={contract_version:'qualification-graph-comparison-v1',case_id:caseId,baseline_run_id:'before',current_run_id:'after',
  comparison_status:'REVIEW_REQUIRED',same_source_text:true,mode:'NOTICE_VERSION_COMPARISON',relation_change:'REVIEW_REQUIRED',
  changes:[{id:'one',change_type:'ANALYSIS_INCONSISTENCY',alignment:'EXACT_SOURCE',reason_code:'SAME_SOURCE_DIFFERENT_COVERAGE',before:side,after:side}],
  issues:['DOCUMENT_RELATION_UNRESOLVED'],counts:{ANALYSIS_INCONSISTENCY:1},eligibility_change_asserted:false,db_writes:false,
  baseline_relations:{status:'UNRESOLVED'},current_relations:{status:'UNRESOLVED'}};
(async()=>{
  const browser=await chromium.launch({headless:true});let page;
  try{
    page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(20000);
    page.on('pageerror',e=>errors.push(e.message));
    await page.route('**/api/v1/**',async route=>{
      const request=route.request(),url=new URL(request.url()),p=url.pathname;
      const headers={'access-control-allow-origin':origin,'access-control-allow-credentials':'true','access-control-allow-headers':'Content-Type','access-control-allow-methods':'GET,POST,OPTIONS'};
      const reply=(data,status=200)=>route.fulfill({status,headers,contentType:'application/json',body:JSON.stringify(data)});
      if(request.method()==='OPTIONS')return route.fulfill({status:204,headers});
      if(request.method()==='POST')posts++;
      if(p==='/api/v1/auth/me')return reply(null);
      if(p==='/api/v1/qualification-graph-options')return reply(options);
      if(p===`/api/v1/preflight-cases/${caseId}/qualification-graphs`)return reply(runs);
      if(p===`/api/v1/preflight-cases/${caseId}/qualification-graphs/compare`){
        assert.equal(request.method(),'GET');assert.equal(url.searchParams.get('baseline_run_id'),'before');assert.equal(url.searchParams.get('current_run_id'),'after');
        return fail?reply({error:{code:'GRAPH_STORAGE_UNAVAILABLE',message:'합성 비교 조회 실패'}},503):reply(result);
      }
      unexpected.push(`${request.method()} ${p}`);return reply({error:{message:'예상하지 않은 요청'}},404);
    });
    await page.goto(`${origin}/qualification-graph?caseId=${caseId}`);
    await page.waitForFunction(()=>document.querySelector('select[aria-label="이전 분석"] option[value="before"]'));
    assert.equal(await page.getByRole('button',{name:'현재 차수 그래프 분석',exact:true}).isDisabled(),true);
    await page.getByLabel('이전 분석',{exact:true}).selectOption('before');
    await page.getByLabel('현재 분석',{exact:true}).selectOption('after');
    await page.getByRole('button',{name:'저장된 두 실행 변경 비교',exact:true}).click();
    await page.getByRole('heading',{name:'분석 불일치',exact:true}).waitFor();
    assert.equal(posts,0);checks.push('explicit saved comparison shows inconsistency, not removal, without POST');
    await page.screenshot({path:path.join(out,'01-comparison.png'),fullPage:true});
    fail=true;await page.getByRole('button',{name:'저장된 두 실행 변경 비교',exact:true}).click();
    await page.getByRole('alert').filter({hasText:'합성 비교 조회 실패'}).waitFor();
    assert.equal(await page.getByRole('region',{name:'그래프 변경 비교 결과'}).count(),0);
    assert.equal(posts,0);checks.push('failed comparison clears previous result and never reports unchanged');
    fail=false;await page.getByRole('button',{name:'저장된 두 실행 변경 비교',exact:true}).click();
    await page.getByRole('heading',{name:'분석 불일치',exact:true}).waitFor();
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(out,'02-mobile.png'),fullPage:true});
    assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);
    fs.writeFileSync(path.join(out,'result.json'),JSON.stringify({kind:'SYNTHETIC_HTTP_GRAPH_BROWSER',checks,posts,errors,unexpected,live_model:false,production_db:false},null,2));
    console.log(JSON.stringify({passed:checks.length,posts,kind:'SYNTHETIC_HTTP_GRAPH_BROWSER'}));
  }catch(error){if(page)await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}).catch(()=>{});fs.writeFileSync(path.join(out,'failure.json'),JSON.stringify({error:String(error),errors,unexpected,checks},null,2));throw error;}
  finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
