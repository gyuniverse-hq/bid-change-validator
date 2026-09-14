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
  await page.locator('#copilot-question').fill(question);
  const responsePromise = page.waitForResponse(r=>r.url().endsWith('/copilot/chat'),{timeout:160000});
  await page.getByRole('button',{name:'질문 보내기',exact:true}).click();
  const response = await responsePromise;
  const body = await response.json();
  responses.push({status:response.status(),body});
  assert.equal(response.status(),200);
  assert.equal(body.envelope.processing.task_status,'PASS');
  assert(body.envelope.claims.some(c=>c.method==='semantic'));
  if (checksMode) {
    assert.deepEqual(body.envelope.capabilities, {
      answerable_count:accountIndex === 0 ? 1 : 2, unanswerable_count:0, manual_review_count:0,
    });
    assert.equal(body.envelope.follow_up_targets.length, accountIndex === 0 ? 1 : 2);
    const rendered = body.envelope.claims.map(c=>c.text).join('\n');
    assert.match(rendered, /현장/);
    if (accountIndex === 0) assert.doesNotMatch(rendered, /장비|운반|1227|1257/);
    if (accountIndex === 1) assert.match(rendered, /운반/);
    result.renderedClaims = rendered;
  }
  await page.locator('[data-copilot-version="3.1"]').waitFor();
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
console.log(`PASS: local login -> qualification -> live ${checksMode ? 'answerable checks' : 'profile summary'} (${accounts[accountIndex].username})`);
