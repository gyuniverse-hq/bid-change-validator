/* Real local UI/API/DB recovery and same-browser account switch. No response mocks. */
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
  const browser = await chromium.launch({headless:true,channel:'chrome'});
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const output = process.env.COPILOT_DB_EVIDENCE;
  const requests = [], errors = [], responses = [], pending = [];
  const caseId = process.env.COPILOT_BROWSER_CASE;
  page.setDefaultTimeout(30000);
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if(r.url().includes('/api/v1/')) requests.push({method:r.method(),url:r.url()}); });
  page.on('response', r => {if(r.url().includes('/qualification-judgments') && r.request().method()==='POST')
    pending.push(r.json().then(body=>responses.push({status:r.status(),body})));});
  await page.route('**/*', route => ['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname) ? route.continue() : route.abort());
  async function login(credentials) {
    await page.goto('http://127.0.0.1:5179/login');
    await page.locator('button[type="submit"]:enabled').waitFor();
    await page.locator('#username').fill(credentials.username);
    await page.locator('#password').fill(credentials.password);
    await page.locator('button[type="submit"]').click();
    await page.waitForURL('**/company');
  }
  async function logout(){await page.getByRole('button',{name:'로그아웃',exact:true}).first().click();await page.waitForURL('**/login');}
  try {
    await login(JSON.parse(process.env.COPILOT_BROWSER_CREDENTIALS));
    await page.goto('http://127.0.0.1:5179/qualification?caseId='+caseId);
    await page.getByRole('button',{name:'저장된 분석으로 다시 판정',exact:true}).waitFor();
    assert(await page.getByRole('button',{name:'전체 변경 요건 재검증 제안',exact:true}).isDisabled());
    await page.getByRole('button',{name:'저장된 분석으로 다시 판정',exact:true}).click();
    await page.getByText('참가자격 검토를 완료했습니다.',{exact:false}).waitFor();
    await Promise.all(pending);
    assert.equal(responses.length,2);
    assert(responses.every(r=>r.status===200 && r.body.rule_version==='qualification-rules-v0.3'));
    assert.equal(requests.filter(r=>r.method==='POST' && r.url.includes('/qualification-analysis')).length,0);
    await page.getByRole('button',{name:'전체 변경 요건 재검증 제안',exact:true}).click();
    await page.getByRole('button',{name:'내용 확인 후 실행',exact:true}).click();
    await page.getByText('다시 판정한 자격요건',{exact:false}).waitFor();
    assert.equal(requests.filter(r=>r.url.endsWith('/copilot/actions/confirm')).length,1);
    await page.screenshot({path:path.join(output,'recovery.png'),fullPage:true});
    await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
    await page.locator('#copilot-semantic-processing').check();
    await logout();
    await login(JSON.parse(process.env.COPILOT_BROWSER_SECOND_CREDENTIALS));
    const me = await page.request.get('http://127.0.0.1:18123/api/v1/auth/me');
    assert.equal((await me.json()).company_id,process.env.COPILOT_BROWSER_SECOND_COMPANY);
    await page.goto('http://127.0.0.1:5179/qualification?caseId='+process.env.COPILOT_BROWSER_SECOND_CASE);
    await page.getByRole('button',{name:'AI Copilot',exact:true}).click();
    assert(!(await page.locator('#copilot-semantic-processing').isChecked()));
    assert.equal(await page.locator('[data-copilot-version="3.1"]').count(),0);
    const denied = await page.request.get('http://127.0.0.1:18123/api/v1/preflight-cases/'+caseId);
    assert.equal(denied.status(),403);
    const list = await page.request.get('http://127.0.0.1:18123/api/v1/preflight-cases');
    assert(!(await list.json()).items.some(c=>c.id===caseId));
    await page.goto('http://127.0.0.1:5179/qualification?caseId='+caseId);
    await page.getByRole('button',{name:'화면 정보 다시 조회',exact:true}).waitFor();
    assert.equal(await page.getByRole('button',{name:'저장된 분석으로 다시 판정',exact:true}).count(),0);
    assert.deepEqual(errors,[]);
    await page.screenshot({path:path.join(output,'account-switch.png'),fullPage:true});
    fs.writeFileSync(path.join(output,'recovery-browser-results.json'),JSON.stringify({status:'PASS',requests,errors,
      recoveredRule:responses.map(r=>r.body.rule_version),foreignCaseStatus:denied.status(),consentReset:true},null,2));
    console.log('PASS old-rule hidden -> explicit saved-analysis rejudgment -> revalidation -> logout -> foreign account denied, consent cleared');
  } catch(e) {
    fs.writeFileSync(path.join(output,'recovery-browser-results.json'),JSON.stringify({status:'FAIL',requests,errors,error:String(e)},null,2));
    await page.screenshot({path:path.join(output,'recovery-failed.png'),fullPage:true});
    throw e;
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
