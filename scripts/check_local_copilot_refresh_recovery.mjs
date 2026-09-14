// Actual Chrome/UI -> persistent evaluation API/DB. No API mocks; no user answers written.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const output = path.join(root, '.ci-results/user-evaluation');
if (!process.env.PLAYWRIGHT_MODULE) throw Error('Set PLAYWRIGHT_MODULE to the installed Playwright index.js');
const loaded = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const chromium = loaded.chromium ?? loaded.default?.chromium;
const accounts = JSON.parse(fs.readFileSync(path.join(output, 'accounts.private.json'), 'utf8'));
const checksMode = process.argv.includes('--checks');
const accountIndex = process.argv.includes('--j14') ? 1 : 0;
const question = checksMode ? '추가 답변이 필요한 확인 질문을 알려줘.' : '판정에 사용한 회사정보만 요약해줘.';
const evidence = path.join(output, 'browser-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(evidence);
const browser = await chromium.launch({headless:true, channel:'chrome'});
const page = await browser.newPage({viewport:{width:1440,height:1000}});
const errors = [], failures = [], responses = [];
page.setDefaultTimeout(60000);
page.on('pageerror', error => errors.push(error.message));
page.on('response', response => {
  // Required-auth /me returns 401 on the unauthenticated login page.
  if (response.url().endsWith('/auth/me') && response.status() === 401 && page.url().endsWith('/login')) return;
  if (response.url().includes('/api/v1/') && response.status() >= 400) failures.push({url:response.url(),status:response.status()});
});
let result = {status:'FAIL',scope:'Real Chrome, persistent local accounts/API/DB; live model; not human evaluation', question, account:accounts[accountIndex].username};
try {
  await page.goto('http://127.0.0.1:5181/login');
  await page.waitForFunction(() => !document.querySelector('button[type="submit"]')?.disabled);
  await page.locator('#username').fill(accounts[accountIndex].username);
  await page.locator('#password').fill(accounts[accountIndex].password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/company');
  await page.goto(accounts[accountIndex].url);
  await page.getByRole('button',{name:'다시 검토',exact:true}).waitFor();
  assert(await page.getByText('전체 조건 검토가 완료되지 않았습니다',{exact:true}).count());
  const read = await page.request.post('http://127.0.0.1:18125/api/v1/copilot/chat', {data:{case_id:accounts[0].case_id,message:'현재 판정 결과',intent:'QUALIFICATION_SUMMARY'}});
  const payload=await read.json();
  responses.push({status:read.status(),body:payload});
  assert.equal(read.status(),200);
  assert.equal(payload.product_state.provenance.judgment_run_id,'bbf456f8-6aaa-4825-af31-3c79aa008ab8');
  assert.equal(payload.product_state.judgment_counts.UNKNOWN,0);
  let blocked=0;
  await page.route('**/api/v1/**',async route=>{
    if(route.request().method()==='POST') { blocked++; await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{code:'TEST_ANALYSIS_UNAVAILABLE',message:'의도한 재검토 실패'}})}); }
    else await route.continue();
  });
  await page.getByRole('button',{name:'다시 검토',exact:true}).click();
  await page.getByText(/저장된 판정을 다시 표시합니다/).waitFor();
  assert(blocked>0);
  assert(await page.getByRole('button',{name:'다시 검토',exact:true}).isEnabled());
  result.controlledFailure=true;
  result.failedPostsBlocked=blocked;
  result.scope='Real local login/latest saved judgment GET; synthetic 503 injected for all review POSTs, no model or database writes';
  assert.deepEqual(errors,[]);
  assert(failures.every(f=>f.status===503));
  result.status='PASS';
} catch(error) {
  result.failure=error.message;
  throw error;
} finally {
  await page.screenshot({path:path.join(evidence,'browser.png'),fullPage:true});
  fs.writeFileSync(path.join(evidence,'browser-verification.json'),JSON.stringify({...result,errors,failures,responses},null,2));
  await browser.close();
}
console.log('PASS: real saved judgment read and controlled review-failure recovery; no writes/model');
