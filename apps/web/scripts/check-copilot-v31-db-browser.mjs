/* Real local UI/login/API/PostgreSQL. No API interception or product mocks. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
async function loadPlaywright() {
  const moduleRoot = process.env.PLAYWRIGHT_MODULE;
  if (!moduleRoot) return import('playwright');
  const entry = moduleRoot.endsWith('/index.js') || moduleRoot.endsWith('\\index.js')
    ? moduleRoot
    : `${moduleRoot.replace(/[\\/]$/, '')}/index.js`;
  return import(pathToFileURL(entry).href);
}

const loadedPlaywright = await loadPlaywright();
const playwright = loadedPlaywright.default ?? loadedPlaywright;
const chromium = loadedPlaywright.chromium ?? playwright.chromium;
if (!chromium) throw Error('Playwright chromium export not found');

(async () => {
  const browser = await chromium.launch({ headless: true, channel: 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [], chats = [], failures = [], pendingResponses = [];
  const output = process.env.COPILOT_DB_EVIDENCE;
  const live = process.env.COPILOT_BROWSER_LIVE === '1';
  page.setDefaultTimeout(60000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('response', response => {
    if (response.url().endsWith('/copilot/chat')) pendingResponses.push(
      response.json().then(body => chats.push({ status: response.status(), body })));
    if (response.status() >= 400 && response.url().includes('/api/v1/')) failures.push({url:response.url(),status:response.status()});
  });
  await page.route('**/*', route => {
    const url = new URL(route.request().url());
    return ['127.0.0.1', 'localhost'].includes(url.hostname) ? route.continue() : route.abort();
  });
  try {
    await page.goto('http://127.0.0.1:5179/login');
    const credentials = JSON.parse(process.env.COPILOT_BROWSER_CREDENTIALS);
    await page.waitForFunction(() => !document.querySelector('button[type="submit"]')?.disabled);
    await page.locator('#username').fill(credentials.username);
    await page.locator('#password').fill(credentials.password);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL('**/company', { timeout: 30000 });
    await page.goto('http://127.0.0.1:5179/qualification?caseId=' + process.env.COPILOT_BROWSER_CASE);
    await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
    await page.locator('#copilot-panel[open]').waitFor();
    assert(!(await page.locator('#copilot-semantic-processing').isChecked()));
    if (live) await page.locator('#copilot-semantic-processing').check();
    await page.locator('#copilot-question').fill('추가 답변이 필요한 확인 질문을 알려줘.');
    await page.getByRole('button', { name: '질문 보내기', exact: true }).click();
    await page.locator('[data-copilot-version="3.1"]').waitFor();
    await page.locator('details[aria-label="답변에서 확인한 항목"] > summary').last().click();
    await page.getByRole('button', { name: '추가 확인 질문 1 · 이 항목 근거 보기', exact: true }).click();
    await page.waitForFunction(() => document.querySelectorAll('[data-copilot-version="3.1"]').length === 2);
    const answerDetails = await page.locator('[data-copilot-version="3.1"]').last().locator('details:has(blockquote)').all();
    for (const detail of answerDetails) if (!(await detail.getAttribute('open'))) await detail.locator(':scope > summary').click();
    assert(await page.locator('[data-copilot-version="3.1"] blockquote').last().isVisible());
    await Promise.all(pendingResponses);
    assert.equal(chats.length, 2);
    assert(chats.every(r => r.status === 200 && r.body.envelope.claims.length && !r.body.envelope.clarification));
    assert.equal(chats[1].body.envelope.context_revision, 2);
    assert(chats[1].body.envelope.processing.tools.some(t => t.tool === 'READ_CHECKS'));
    if (live) {
      assert(chats.every(r => r.body.envelope.claims.some(c => c.method === 'semantic')));
      assert(chats.every(r => r.body.envelope.processing.task_status === 'PASS'));
      const firstText = chats[0].body.envelope.claims.map(c => c.text).join(' ');
      assert(firstText.includes('정보통신공사업') && /6억|600,000,000/.test(firstText));
      await page.locator('#copilot-question').fill('판정에 사용한 회사정보만 요약해줘.');
      await page.getByRole('button', { name: '질문 보내기', exact: true }).click();
      await page.waitForFunction(() => document.querySelectorAll('[data-copilot-version="3.1"]').length === 3);
      await Promise.all(pendingResponses);
      assert.equal(chats.length, 3);
      const profile = chats[2].body.envelope;
      assert.equal(profile.processing.task_status, 'PASS');
      assert(profile.claims.some(c => c.method === 'semantic'));
      const text = profile.claims.map(c => c.text).join(' ');
      assert(text.includes('서울') && text.includes('8') && /5억|500,000,000/.test(text));
      assert.equal(profile.context_revision, 3);
      assert(chats.every(r => !r.body.envelope.actions.length));
      await page.locator('[data-copilot-version="3.1"]').last().screenshot({path:path.join(output, 'profile.png')});
    }
    assert.deepEqual(errors, []);
    assert.deepEqual(failures, []);
    await page.locator('#copilot-panel').screenshot({ path: path.join(output, 'browser.png') });
    fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify({status:'PASS',scope:live ? 'real browser/login/HTTP/API/DB/model' : 'real browser/login/API/DB; model disabled',chats,errors,failures}, null, 2));
    console.log('PASS: browser login -> API -> PostgreSQL -> chat -> selected target -> citation; model ' + (live ? 'enabled' : 'disabled'));
  } catch(error) {
    await Promise.allSettled(pendingResponses);
    fs.writeFileSync(path.join(output, 'browser-results.json'), JSON.stringify({status:'FAIL',live,chats,errors,failures}, null, 2));
    await page.screenshot({ path: path.join(output, 'browser-failed.png') });
    console.error(JSON.stringify({errors,failures,text:(await page.locator('body').innerText()).slice(-4000)}));
    throw error;
  } finally { await browser.close(); }
})().catch(error => {
  const secret = JSON.parse(process.env.COPILOT_BROWSER_CREDENTIALS || '{}');
  let message = String(error.stack || error);
  for (const value of Object.values(secret)) message = message.split(value).join('[REDACTED]');
  console.error(message); process.exit(1);
});
