/* Real local evaluation UI -> authenticated API -> DB/model. No product mocks. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { fileURLToPath, pathToFileURL } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const state = path.join(root, '.ci-results/user-evaluation');
const output = path.join(state, 'job-browser-' + new Date().toISOString().replace(/[:.]/g, '-'));
fs.mkdirSync(output);
const accounts = JSON.parse(fs.readFileSync(path.join(state, 'core-accounts.private.json')));
const account = accounts.find(a => a.username === 'eval-j05');
const { chromium } = await import(pathToFileURL(process.env.PLAYWRIGHT_MODULE).href);
const browser = await chromium.launch({ headless: true, channel: 'chrome' });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const report = { status: 'RUNNING', scope: 'real UI/login/API/local DB/model; no business writes', chats: [], errors: [], writes: [] };
page.setDefaultTimeout(180000);
page.on('pageerror', error => report.errors.push(error.message));
await page.route('**/*', route => {
  const request = route.request(), url = new URL(request.url());
  if (!['127.0.0.1', 'localhost'].includes(url.hostname)) return route.abort();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && url.pathname.startsWith('/api/') &&
      !['/api/v1/auth/login', '/api/v1/copilot/chat'].includes(url.pathname)) {
    report.writes.push(url.pathname); return route.abort();
  }
  return route.continue();
});
try {
  await page.goto('http://127.0.0.1:5181/login');
  await page.waitForFunction(() => !document.querySelector('button[type="submit"]')?.disabled);
  await page.locator('#username').fill(account.username);
  await page.locator('#password').fill(account.password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/company', { timeout: 30000 });
  console.log('Login complete; opening Core case');
  await page.goto(account.url);
  await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
  await page.locator('#copilot-semantic-processing').check();
  await page.locator('#copilot-document-processing').check();
  const questions = [
    '이 공고에 참여할 준비를 하고 있어. 저장된 우리 회사 판정과 추가로 확인할 일, 공고의 제출 서류와 마감일을 함께 정리해줘.',
    '처음 요청에서 아직 해결하지 못한 내용을 이어서 검토하고 남은 일을 알려줘. 값을 저장하거나 새 판정을 실행하지 마.',
  ];
  for (const question of questions) {
    await page.locator('#copilot-question').fill(question);
    const response = page.waitForResponse(r => r.url().endsWith('/api/v1/copilot/chat'), { timeout: 180000 });
    await page.getByRole('button', { name: '질문 보내기', exact: true }).click();
    const result = await response;
    const body = await result.json();
    report.chats.push({ status: result.status(), body });
    console.log('Chat', report.chats.length, result.status(), body.envelope?.processing?.task_status);
    assert.equal(result.status(), 200);
    assert(body.envelope.job && body.envelope.job.goal === questions[0]);
    assert.equal(body.envelope.actions.length, 0);
    await page.waitForFunction(n => document.querySelectorAll('[data-copilot-version="3.1"]').length === n, report.chats.length);
  }
  const last = report.chats.at(-1).body.envelope;
  assert.equal(last.job.status, 'COMPLETE');
  assert.equal(last.processing.task_status, 'PASS');
  const answer = page.locator('[data-copilot-version="3.1"]').last();
  await answer.locator('.copilot-job-progress > summary').click();
  assert(await answer.getByText(questions[0], { exact: true }).isVisible());
  await page.locator('#copilot-panel').screenshot({ path: path.join(output, 'desktop.png') });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForFunction(() => document.querySelector('#copilot-panel').matches(':modal'));
  assert((await page.locator('#copilot-panel').boundingBox()).width <= 390);
  await page.locator('#copilot-panel').screenshot({ path: path.join(output, 'mobile.png') });
  await page.getByRole('button', { name: '도우미 닫기' }).click();
  await page.getByRole('button', { name: 'AI Copilot', exact: true }).click();
  assert.equal(await page.locator('[data-copilot-version="3.1"]').count(), 2);
  assert.deepEqual(report.errors, []);
  assert.deepEqual(report.writes, []);
  report.status = 'PASS';
  console.log('PASS: compound job and resume through real UI/API/DB/model; purpose retained; no business writes; mobile/reopen');
} catch (error) {
  report.status = 'FAIL'; report.failure = String(error);
  await page.screenshot({ path: path.join(output, 'failed.png') });
  process.exitCode = 1;
  console.error(String(error));
} finally {
  fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify(report, null, 2));
  console.log('EVIDENCE_DIR=' + output);
  await browser.close();
}
