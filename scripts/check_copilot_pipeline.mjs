// One browser job captures UI + actual HTTP/model traces; never replays a call through a second API test.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const folder=path.resolve(process.argv[2]);
if(fs.existsSync(path.join(folder,'pause-browser-jobs'))){
 throw new Error('Pipeline paused: inspect the recorded blocker before starting another paid Job');
}
const selected=process.argv[3];
const repeat=process.argv.includes('--repeat');
const resumeIndex=process.argv.indexOf('--resume-report');
const resume=resumeIndex>=0?JSON.parse(fs.readFileSync(process.argv[resumeIndex+1])):null;
const labelIndex=process.argv.indexOf('--account-label');
const manifest=JSON.parse(fs.readFileSync(path.join(folder,'manifest.json')));
assert.equal(manifest.gates.G2,'PASS','G2 must pass before paid browser jobs');
const own=JSON.parse(fs.readFileSync(path.join(folder,'accounts.private.json')));
const core=JSON.parse(fs.readFileSync(path.join(folder,'../core-accounts.private.json')));
const jobs={
 N1:{label:'J13',questions:[
  '기준 공고와 현재 공고에서 실제로 바뀐 조건과 표현만 달라진 것을 구분하고, 같은 회사정보로 비교한 영향과 내가 할 일을 알려줘.',
  '그러면 업종이 1224에서 1227로 바뀌어서 우리 회사가 참가 가능에서 불가가 된 거야? 개별 요건 변화와 전체 결과를 나눠 짧게 설명해줘.',
  '앞서 말한 업종 변경의 원문 근거를 보여주고, 아직 내가 확인할 일만 정리해줘.']},
 N2:{label:'J14',questions:[
  '기준과 현재 공고를 비교해서 우리 회사가 영향을 받는 조건과 결과를 설명하고, 대응할 일을 정리해줘.',
  '우리 회사 업종은 1257과 1224인데, 현재 수집·운반 요건이 미달인 직접 이유가 뭐야?',
  '내가 지금 확인할 일만 알려줘. 이미 설명한 변화는 반복하지 마.']},
 N3:{label:'J15',questions:[
  '우리 회사에는 수집·운반업 등록이 없는데 그 요건을 충족한다는 저장 결과가 나온 이유와 확인할 근거를 설명해줘.',
  '그러면 운반할 트럭만 있으면 충분하다는 뜻이야?',
  '그 예외의 원문 조건과 내가 실제로 확인해야 하는 자료를 정리해줘.']},
 N4:{label:repeat?'J16-repeat':'J16-action',questions:[
  '추가 답변이 필요한 확인 질문과, 우리 회사에서 수집·운반 요건이 아직 미확인인 이유를 설명해줘.',
  '처분 허가, 법적으로 직접 운반할 허가 조건, 필요한 장비 조건을 모두 충족한다고 가정하면 어떻게 돼? 저장은 하지 마.',
  '해당 폐기물의 처분 허가가 있고 법적으로 직접 운반할 허가 조건과 필요한 장비 조건을 모두 충족해. 증빙도 보유하고 있어. 이 확인 항목에 답변을 반영할 제안을 만들어줘. 아직 실행하지 마.'],execute:true},
 C1:{account:'eval-j05',questions:[
  '우리 회사가 이 공고에 참여하려고 해. 현재 회사 정보로 충족하는 조건과 추가로 확인할 사항을 정리하고, 제출할 서류와 각각의 마감일·제출 방법까지 확인해서 준비 순서를 알려줘. 근거가 부족한 부분은 따로 표시해줘.',
  '처음 부탁한 참여 준비에서 아직 확인하지 못한 항목이 정확히 뭐야? 확인할 수 있는 것은 이어서 확인하고, 끝내 확인할 수 없는 것은 이유와 내가 해야 할 행동을 알려줘. 이미 설명한 내용은 반복하지 마.',
  '지금까지 내용을 바탕으로 내가 실행할 체크리스트를 만들어줘. 필수 제출과 참고·협조사항을 구분하고, 마감일이 지난 일정은 따로 표시해줘.']},
 C2:{account:'eval-j01',questions:[
  '기준 공고에서 현재 공고로 바뀌면서 삭제된 자격 요건과 남아 있는 요건을 구분하고, 회사에 미치는 영향과 대응할 일을 설명해줘.',
  '삭제된 요건은 우리 회사가 충족한 것으로 바뀐 거야?',
  '현재 공고에서 아직 확인할 자격 조건과 그 원문 근거만 정리해줘.']},
 C3:{account:'eval-j09',questions:[
  '기준과 현재 공고에서 달라진 메타데이터와 실제 자격 조건을 구분하고, 회사 판정이 바뀌는지 설명해줘.',
  '표시가 달라졌다는 이유만으로 참가 가능 여부도 달라졌다고 볼 수 있어?',
  '그 판단의 근거와 내가 추가 확인할 일만 정리해줘.']},
};
assert(jobs[selected],'Choose N1-N4 or C1-C3');
const job=jobs[selected];
const override=labelIndex>=0?process.argv[labelIndex+1]:null;
assert(!override||(selected==='N4'&&manifest.execution_copies?.some(c=>c.label===override)),'Only registered N4 execution copies may override the account label');
const account=job.label?own.find(a=>a.label===(override||job.label)):core.find(a=>a.username===job.account);
assert(account);
assert(!resume||(selected==='N4'&&resume.case_id===account.case_id&&resume.execution?.http===200),'Only readback of a recorded successful N4 execution can resume');
const out=path.join(folder,`${selected}${repeat?'-repeat':''}${resume?'-recovery':''}-${Date.now()}`);fs.mkdirSync(out);
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,channel:'chrome'});
const context=await browser.newContext({viewport:{width:1440,height:1100}});
const page=await context.newPage();page.setDefaultTimeout(30000);
const runtime=JSON.parse(fs.readFileSync(path.join(folder,'../server.json')));
const report={job:selected,repeat,case_id:account.case_id,runtime,worker_pid:process.pid,steps:[],page_errors:[],blocked:[],semantic_review:'PENDING',data_boundary:'local public snapshots and synthetic profiles only'};
if(resume){Object.assign(report,{steps:resume.steps.filter(s=>s.body.envelope),before:resume.before,before_execution:resume.before_execution,execution:resume.execution,recovery_of:path.resolve(process.argv[resumeIndex+1]),recovery_context:'fresh login; existing saved result read only; original execution not repeated'});}
page.on('pageerror',e=>report.page_errors.push(e.message));
let executionAllowed=false;
await page.route('**/*',route=>{
 const r=route.request(),u=new URL(r.url());
 if(!['localhost','127.0.0.1'].includes(u.hostname))return route.abort();
 if(u.pathname.startsWith('/api/')&&!['GET','HEAD','OPTIONS'].includes(r.method())&&u.pathname!='/api/v1/auth/login'){
  const payload=r.postDataJSON();
  const chat=u.pathname==='/api/v1/copilot/chat'&&payload?.case_id===account.case_id;
  const execute=executionAllowed&&u.pathname==='/api/v1/copilot/actions/confirm'
    &&payload?.action?.expected?.case_id===account.case_id
    &&payload?.action?.action_type==='ANSWER_REQUIREMENT'&&payload.confirmed===true;
  if(!chat&&!execute){report.blocked.push(u.pathname);return route.abort();}
 }
 return route.continue();
});
const endpoint=`http://127.0.0.1:18125/api/v1/preflight-cases/${account.case_id}/qualification-judgment-runs`;
const save=()=>fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));
save();console.log('START='+selected+' REPORT='+path.join(out,'report.json'));
async function ask(question){
 const started=Date.now();await page.locator('#copilot-question').fill(question);
 const waiting=page.waitForResponse(r=>r.url().endsWith('/copilot/chat')&&r.request().method()==='POST'&&r.request().postDataJSON()?.message===question,{timeout:180000});
 await page.getByRole('button',{name:'질문 보내기',exact:true}).click();
 const response=await waiting,body=await response.json();
 report.steps.push({question,http:response.status(),elapsed_ms:Date.now()-started,body});save();
 console.log(JSON.stringify({job:selected,turn:report.steps.length,http:response.status(),elapsed_ms:Date.now()-started,status:body.envelope?.processing?.task_status,claims:body.envelope?.claims?.filter(c=>c.reason!=='EXACT_SOURCE').map(c=>c.text)}));
 assert.equal(response.status(),200);assert(body.envelope?.claims?.length||body.envelope?.clarification,'Empty answer');
 const firstClaim=body.envelope?.claims?.[0]?.text ?? '';
 // HTTP success does not prove the matching user turn received its response.
 // In particular a concurrent action readback must not discard this answer.
 await page.waitForFunction(({question,firstClaim})=>{
  const turn=[...document.querySelectorAll('.copilot-turn')].findLast(t=>t.querySelector('.copilot-question')?.textContent===question);
  const answer=turn?.querySelector('article.copilot-answer');
  const compact=s=>s.replace(/\s+/g,'');
  return Boolean(answer && (!firstClaim || compact(answer.textContent).includes(compact(firstClaim))));
 },{question,firstClaim},{timeout:15000});
 report.steps.at(-1).visible_answer_confirmed=true;save();
 await page.getByRole('button',{name:'질문 보내기',exact:true}).waitFor({state:'visible'});
 return body.envelope;
}
try{
 await page.goto('http://127.0.0.1:5181/login');await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 await page.locator('#username').fill(account.username);await page.locator('#password').fill(account.password);
 await page.locator('button[type="submit"]').click();await page.waitForURL('**/company');
 await page.goto(account.url);await page.waitForLoadState('networkidle');
 if(resume)report.recovery_before=await(await page.request.get(endpoint)).json();
 else report.before=await(await page.request.get(endpoint)).json();
 if(job.execute&&!resume)assert.equal(report.before[0]?.unknown_count,1,'Use a fresh J16 execution case; never reset or repeat an already consumed case');
 await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
 await page.locator('#copilot-semantic-processing').check();
 await page.locator('#copilot-document-processing').check();
 if(!resume)for(const question of job.questions)await ask(question);
 if(!resume&&job.execute&&report.steps.at(-1).body.envelope?.clarification
    &&!report.steps.at(-1).body.envelope?.actions?.length){
  report.answer_clarification='One explicit answer to the product clarification; no payload substitution or automatic execution.';
  await ask('각 조건에 대한 제 답변은 다음과 같아. 해당 폐기물 처분 허가: 예. 법적으로 직접 수집·운반할 허가 조건: 예. 필요한 장비 조건: 예. 증빙 보유: 예. 이 답변으로 제안을 만들어줘. 아직 실행하지 마.');
 }
 if(!resume&&!job.execute&&report.steps.at(-1).body.envelope?.job?.status==='OPEN'){
  report.targeted_continuation='One fourth turn for the explicitly unfinished original Job; no unchanged-question retry.';
  await ask('최초 요청에서 아직 검증이 끝나지 않은 부분만 이어서 확인해줘. 이미 검증한 내용은 유지하고, 누락한 서류나 단계가 있으면 해당 원문 근거와 함께 보완해줘. 확인할 수 없는 부분은 이유와 다음 행동을 알려줘.');
 }
 if(!resume)report.before_execution=await(await page.request.get(endpoint)).json();
 assert.deepEqual(report.before_execution,report.before,'Read/hypothesis/proposal wrote a judgment');
 if(job.execute&&!resume){
  const envelope=report.steps.at(-1).body.envelope;
  assert.equal(envelope.actions.length,1,'Model must propose the exact answer without harness substitution');
  const action=envelope.actions[0];
  assert.equal(action.action_type,'ANSWER_REQUIREMENT');assert.equal(action.expected.case_id,account.case_id);
  const values=JSON.parse(action.user_input.normalized_value).answers;
  assert.deepEqual(values,{disposal_permit:true,legal_transport_permission:true,required_equipment:true});
  await page.screenshot({path:path.join(out,'proposal.png'),fullPage:true});
  await page.getByRole('button',{name:/서버 제안 검토/}).last().click();
  await page.getByRole('link',{name:/03 추가정보 화면/}).last().click();
  executionAllowed=true;
  const waiting=page.waitForResponse(r=>r.url().includes('/copilot/actions/')&&r.request().method()==='POST',{timeout:30000});
  await page.getByRole('button',{name:'내용 확인 후 실행',exact:true}).click();
  const response=await waiting;report.execution={http:response.status(),body:await response.json()};save();
  assert.equal(response.status(),200);
  await page.waitForFunction(()=>document.body.textContent.includes('새 판정')||document.body.textContent.includes('반영했습니다'));
  executionAllowed=false;
 }
 if(job.execute)await ask('방금 저장한 답변과 달라진 개별 요건, 현재 종합 판정을 구분해서 설명해줘.');
 if(job.execute){
  await page.getByText('검토 데이터를 불러오고 있습니다.',{exact:true}).waitFor({state:'hidden',timeout:15000});
  report.post_execution_view_settled=true;
 }
 report.after=await(await page.request.get(endpoint)).json();
 if(resume)assert.deepEqual(report.after,report.recovery_before,'Recovery read must not repeat the write');
 if(!job.execute)assert.deepEqual(report.before,report.after);
 report.collapsed_progress=await page.locator('details.copilot-job-progress[open]').count()===0;
 assert(report.collapsed_progress,'Diagnostic panels should start collapsed');
 report.transport='PASS';
}catch(error){report.failure=error.stack;console.error(error.message)}finally{
 await page.screenshot({path:path.join(out,'final.png'),fullPage:true}).catch(()=>{});
 report.visible_text=await page.locator('body').innerText().catch(()=>'');report.finished_utc=new Date().toISOString();save();
 await browser.close();console.log('REPORT='+path.join(out,'report.json'));
 if(report.failure||report.page_errors.length||report.blocked.length)process.exitCode=1;
}
