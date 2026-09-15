import fs from 'node:fs';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
const setupPath=process.argv[2];
const setup=JSON.parse(fs.readFileSync(setupPath));
const folder=setupPath.replace(/setup.private.json$/, 'browser-'+Date.now());
fs.mkdirSync(folder);
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({headless:true,channel:'chrome'});
const page=await browser.newPage({viewport:{width:1440,height:1000}});
page.setDefaultTimeout(30000);
const report={caseId:setup.case_id,steps:[],responses:[],errors:[],blocked:[]};
page.on('pageerror',e=>report.errors.push(e.message));
await page.route('**/*',route=>{
 const req=route.request(),u=new URL(req.url());
 if(!['127.0.0.1','localhost'].includes(u.hostname)) return route.abort();
 if(u.pathname.startsWith('/api/')&&!['GET','HEAD','OPTIONS'].includes(req.method())&&u.pathname!='/api/v1/auth/login'){
  let p;try{p=req.postDataJSON();}catch{}
  const chat=u.pathname==='/api/v1/copilot/chat'&&p?.case_id===setup.case_id;
  const confirm=u.pathname==='/api/v1/copilot/actions/confirm'&&p?.action?.expected?.case_id===setup.case_id&&p?.action?.action_type==='REVALIDATE'&&p.confirmed===true;
  if(!chat&&!confirm){report.blocked.push({path:u.pathname,payload:p});return route.abort();}
 }
 return route.continue();
});
async function capture(name){await page.screenshot({path:folder+'/'+name+'.png',fullPage:true}); const text=await page.locator('body').innerText();fs.writeFileSync(folder+'/'+name+'.txt',text);return text;}
try{
 await page.goto('http://127.0.0.1:5181/login');
 await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
 await page.locator('#username').fill(setup.account.username);await page.locator('#password').fill(setup.account.password);
 await page.locator('button[type="submit"]').click();await page.waitForURL('**/company');
 await page.goto(setup.account.url);await page.waitForLoadState('networkidle');
 await capture('01-before');
 const proposalResponse=page.waitForResponse(r=>r.url().endsWith('/copilot/chat'));
 await page.getByRole('button',{name:'전체 변경 요건 재검증 제안',exact:true}).click();
 const pr=await proposalResponse;report.responses.push({stage:'proposal',status:pr.status(),body:await pr.json()});
 assert.equal(pr.status(),200);
 await capture('02-proposal');
 const confirmed=page.waitForResponse(r=>r.url().endsWith('/copilot/actions/confirm'));
 await page.getByRole('button',{name:'내용 확인 후 실행',exact:true}).click();
 const cr=await confirmed;report.responses.push({stage:'confirm',status:cr.status(),body:await cr.json()});
 assert.equal(cr.status(),200);
 await page.getByText('영향 있는 변경',{exact:false}).first().waitFor();
 const after=await capture('03-result');
 assert.match(after,/1224/);assert.match(after,/1227/);
 report.steps.push({step:'revalidation_and_source_comparison',status:'PASS'});
 await page.reload();await page.waitForLoadState('networkidle');
 const reload=await capture('04-reload');
 report.steps.push({step:'reload_persists_comparison',status:reload.includes('영향 있는 변경')?'PASS':'FAIL'});
 await page.goto(`http://127.0.0.1:5181/evidence?caseId=${setup.case_id}`);await page.waitForLoadState('networkidle');
 const evidence=await capture('05-evidence');assert.match(evidence,/1227/);
 report.steps.push({step:'current_original_evidence',status:'PASS'});
}catch(e){report.failure=e.message;}finally{
 fs.writeFileSync(folder+'/report.json',JSON.stringify(report,null,2));
  console.log(JSON.stringify({folder,steps:report.steps,failure:report.failure,errors:report.errors,blocked:report.blocked}));
  await browser.close();
  if (report.failure || report.errors.length || report.blocked.length || report.steps.some(s => s.status !== 'PASS')) process.exitCode=1;
}
