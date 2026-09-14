/* 실제 프로젝트 타입 검사에서 발견한 오류 응답 경계의 회귀 테스트. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

class ApiError extends Error {
  constructor(message, status, code) { super(message); this.status = status; this.code = code; }
}
function ports(payload) {
  const file = path.resolve(__dirname, '../lib/qualification-detail-api.ts');
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  });
  const mod = { exports: {} };
  const mocks = {
    '@/lib/api': { ApiError, apiFetch: async () => ({ ok: false, status: 503, json: async () => payload }) },
    '@/lib/qualification-api': {}, '@/lib/qualification-state-api': {}, '@/lib/qualification-detail': {},
  };
  new Function('require', 'module', 'exports', compiled.outputText)(name => {
    assert(Object.hasOwn(mocks, name), `Unexpected dependency ${name}`);
    return mocks[name];
  }, mod, mod.exports);
  return mod.exports.detailReadPorts();
}
for (const [name, payload] of Object.entries({
  nullBody: null, empty: {}, text: 'unavailable', missing: { status: 'failed' },
  nullError: { error: null }, numberError: { error: 42 },
  invalidFields: { error: { message: ['not a message'], code: { token: 'not a code' } } },
})) test(`detail GET error boundary: ${name}`, async () => {
  await assert.rejects(ports(payload).getCase('case'), error =>
    error instanceof ApiError && error.status === 503 && error.code === 'HTTP_ERROR'
    && error.message === '검토 정보를 불러오지 못했습니다.');
});
test('detail GET preserves validated structured error', async () => {
  await assert.rejects(ports({ error: { message: '다시 조회해 주세요.', code: 'STATE_CHANGED' } }).getCase('case'),
    error => error.status === 503 && error.code === 'STATE_CHANGED' && error.message === '다시 조회해 주세요.');
});
