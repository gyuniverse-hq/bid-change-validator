// Re-render saved results only. No model calls, proposals, judgments or writes.
import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const root=process.cwd(),folder=path.resolve(process.argv[2]);
const basis=JSON.parse(fs.readFileSync(path.join(folder,'ui-recheck-input.json')));
const hash=p=>createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const checkBasis=()=>basis.covered_paths.forEach(p=>assert.equal(hash(path.join(root,p)),basis.product[p]));
checkBasis();
const accounts=JSON.parse(fs.readFileSync(path.join(folder,'accounts.private.json')));
const {chromium}=await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser=await chromium.launch({channel:'chrome',headless:true});
const checks=[],artifacts=[];
try {
 for(const label of ['J13','J14']){
  const a=accounts.find(x=>x.label===label),context=await browser.newContext({viewport:{width:1440,height:1100}});
  const page=await context.newPage(),blocked=[],errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>{
   const r=route.request(),u=new URL(r.url());
   if(!['localhost','127.0.0.1'].includes(u.hostname))return route.abort();
   if(u.pathname.startsWith('/api/')&&!['GET','HEAD','OPTIONS'].includes(r.method())&&u.pathname!='/api/v1/auth/login'){
    blocked.push(u.pathname);return route.abort();
   } return route.continue();
  });
  await page.goto('http://127.0.0.1:5181/login');
  await page.waitForFunction(()=>!document.querySelector('button[type="submit"]')?.disabled);
  await page.locator('#username').fill(a.username);await page.locator('#password').fill(a.password);
  await page.locator('button[type="submit"]').click();await page.waitForURL('**/company');
  const endpoint=`http://127.0.0.1:18125/api/v1/preflight-cases/${a.case_id}/qualification-revalidation`;
  const before=await(await page.request.get(endpoint)).json();
  fs.writeFileSync(path.join(folder,`ui-recheck-${label}-data.json`),JSON.stringify(before,null,2));
  await page.goto(a.url);await page.waitForFunction(()=>document.body.innerText.includes('구조화 값이 바뀐 것'));
  const text=await page.locator('main').innerText();
  const count=Number(text.match(/구조화 값이 바뀐 것\s*(\d+)건/)[1]);
  assert.equal(count,1,'Only transport code changes the structured condition');
  assert(text.includes('1224 → 1227'));
  assert.equal(await page.getByText('구조화 값 변경',{exact:true}).count(),1);
  assert.equal(await page.getByText('구조화 값 동일 · 원문·근거 차이',{exact:true}).count(),3);
  assert.deepEqual(await(await page.request.get(endpoint)).json(),before);
  assert.deepEqual(blocked,[]);assert.deepEqual(errors,[]);
  const file=path.join(folder,`ui-recheck-${label}.png`);await page.screenshot({path:file,fullPage:true});
  artifacts.push({path:path.relative(root,file),sha256:hash(file)});
  checks.push({label,status:'PASS',structured_changed_count:count,model_calls:0,writes:0,revalidation_unchanged:true});
  await context.close();
 }
 checkBasis();
 fs.writeFileSync(path.join(folder,'ui-recheck.json'),JSON.stringify({...basis,status:'PASS',checks,artifacts},null,2));
 console.log(JSON.stringify(checks));
} finally {await browser.close();}
