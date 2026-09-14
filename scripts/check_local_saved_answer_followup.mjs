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
  await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
  await page.locator('#copilot-panel[open]').waitFor();
  assert.equal(await page.locator('#copilot-semantic-processing').isChecked(), false);
  await page.locator('#copilot-semantic-processing').check();
  const questions=['방금 반영한 내용과 현재 판정을 설명해줘','확인서를 제출했다고 가정하면 어떻게 돼?','아까 답변을 잘못했어. 수정하려면 어떻게 해야 해?'];
  for (const [index,question] of questions.entries()) {
    await page.locator('#copilot-question').fill(question);
    const pending=page.waitForResponse(r=>r.url().endsWith('/copilot/chat'));
    await page.getByRole('button',{name:'질문 보내기',exact:true}).click();
    const response=await pending;
    const body=await response.json();
    responses.push({question,status:response.status(),body});
    assert.equal(response.status(),200);
    assert.equal(body.envelope.processing.task_status,'PASS');
    assert.equal(body.envelope.processing.calls.length,0);
    assert.equal(body.envelope.actions.length,0);
    assert.deepEqual(body.envelope.processing.plan.tasks.map(t=>t.kind),['READ_JUDGMENT']);
    if(index===0){assert.match(body.answer,/확인서 미제출/);assert.match(body.answer,/미달 2건/);assert.doesNotMatch(body.answer,/지역.*추가|예외가 추가/);}
    if(index===1){assert.match(body.answer,/가정/);assert.match(body.answer,/다른 미달 요건/);assert.match(body.answer,/재판정은 하지 않았습니다/);}
    if(index===2){assert.match(body.answer,/직접 수정하는 기능이 없습니다/);assert.doesNotMatch(body.answer,/제출된 입찰서는 취소/);}
  }
  result.scope='Three actual user follow-ups through real Chrome/API/persisted J13; deterministic, no model and no writes';
  await page.locator('[data-copilot-version="3.1"]').last().waitFor();
  assert.deepEqual(errors,[]);
  assert.deepEqual(failures,[]);
  result.status='PASS';
} catch(error) {
  result.failure=error.message;
  throw error;
} finally {
  await page.screenshot({path:path.join(evidence,'browser.png'),fullPage:true});
  fs.writeFileSync(path.join(evidence,'browser-verification.json'),JSON.stringify({...result,errors,failures,responses},null,2));
  await browser.close();
}
console.log('PASS: three persisted-answer follow-ups; no model calls or actions');
