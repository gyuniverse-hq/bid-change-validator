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
const accountIndex = 0;
const question = '이 공고에서 제출해야 하는 서류와 마감일을 알려줘.';
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
  await page.locator('#copilot-document-processing').check();
  await page.locator('#copilot-question').fill(question);
  const pending=page.waitForResponse(r=>r.url().endsWith('/copilot/chat'),{timeout:180000});
  await page.getByRole('button',{name:'질문 보내기',exact:true}).click();
  const response=await pending;
  const body=await response.json();
  responses.push({question,status:response.status(),body});
  assert.equal(response.status(),200);
  assert.equal(body.envelope.actions.length,0);
  assert.equal(body.envelope.processing.task_status,'PASS');
  assert.match(body.answer,/2026[.년\s]*8[.월\s]*25/);
  assert.match(body.answer,/10:00|10시/);
  assert.match(body.answer,/현장.*확인/);
  assert.match(body.answer,/청렴/);
  assert.doesNotMatch(body.answer,/제출 마감일과 마감 시각이 포함되어 있지|서류의 종류를 확정할 수 없습니다/);
  result.scope='Actual Chrome/API/local notice; live model; read only documents and deadlines question';
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
console.log('PASS: document/deadline question; evidence=' + evidence);
