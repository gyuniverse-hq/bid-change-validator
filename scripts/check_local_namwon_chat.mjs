import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const setupPath=process.argv[2],setup=JSON.parse(fs.readFileSync(setupPath));
const folder=setupPath.replace(/setup.private.json$/,'chat-'+Date.now());fs.mkdirSync(folder);
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,channel:'chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});page.setDefaultTimeout(30000);
const report={steps:[],errors:[],blocked:[]};
page.on('pageerror',e=>report.errors.push(e.message));
await page.route('**/*',route=>{
 const r=route.request(),u=new URL(r.url());
 if(!['localhost','127.0.0.1'].includes(u.hostname))return route.abort();
 if(u.pathname.startsWith('/api/')&&!['GET','HEAD','OPTIONS'].includes(r.method())&&u.pathname!='/api/v1/auth/login'){
  if(u.pathname!='/api/v1/copilot/chat'||r.postDataJSON()?.case_id!==setup.case_id){report.blocked.push(u.pathname);return route.abort();}
 }
 return route.continue();
});
try{
 await page.goto('http://127.0.0.1:5181/login');await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 await page.locator('#username').fill(setup.account.username);await page.locator('#password').fill(setup.account.password);
 await page.locator('button[type="submit"]').click();await page.waitForURL('**/company');
 await page.goto(setup.account.url);await page.waitForLoadState('networkidle');
 const endpoint=`http://127.0.0.1:18125/api/v1/preflight-cases/${setup.case_id}/qualification-judgment-runs`;
 const before=await (await page.request.get(endpoint)).json();
 await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
 await page.locator('#copilot-semantic-processing').check();
 for(const question of ['기준 공고와 현재 공고에서 무엇이 바뀌었고 방금 재검증한 현재 판정은 무엇인지 설명해줘. 원문 표현만 달라진 것과 구조화 값 변경을 구분해줘.','그럼 1224에서 1227로 바뀌어서 우리 회사가 참가 가능에서 불가로 바뀐 거야? 저장된 결과를 기준으로 설명하고 아직 확인할 사항을 알려줘.']){
  const started=Date.now();await page.locator('#copilot-question').fill(question);
  const waiting=page.waitForResponse(r=>r.url().endsWith('/copilot/chat'),{timeout:180000});
  await page.getByRole('button',{name:'질문 보내기',exact:true}).click();const response=await waiting;
  const body=await response.json();const entry={question,http:response.status(),elapsed_ms:Date.now()-started,body};report.steps.push(entry);
  console.log(JSON.stringify({http:entry.http,elapsed_ms:entry.elapsed_ms,status:body.envelope?.processing?.task_status,claims:body.envelope?.claims?.map(c=>c.text)}));
  assert.equal(response.status(),200);assert.equal(body.envelope?.actions?.length,0);
  assert(body.envelope?.claims?.length > 0, 'EMPTY_ANSWER_CANNOT_COMPLETE_A_NEW_QUESTION');
  if (report.steps.length === 2) {
    assert(body.envelope.processing.tools.some(t=>t.tool==='READ_CHECKS'), 'FOLLOWUP_CHECK_REQUEST_WAS_DROPPED');
    assert(body.envelope.claims.some(c=>c.speech_act==='CHECK_REQUEST'), 'FOLLOWUP_HAS_NO_CHECK_GUIDANCE');
  }
  await page.locator('#copilot-question').waitFor();
 }
 const after=await (await page.request.get(endpoint)).json();report.judgments_unchanged=JSON.stringify(before)===JSON.stringify(after);
 assert(report.judgments_unchanged);
}catch(e){report.failure=e.message;}finally{
 await page.screenshot({path:folder+'/chat.png',fullPage:true});
 fs.writeFileSync(folder+'/report.json',JSON.stringify(report,null,2));console.log('REPORT='+folder+'/report.json');await browser.close();
 if(report.failure || report.errors.length || report.blocked.length || report.steps.length!==2 || report.steps.some(s=>s.body.envelope?.processing?.task_status!=='PASS')) process.exitCode=1;
}
