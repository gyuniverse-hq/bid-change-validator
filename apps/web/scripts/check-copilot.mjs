// No test framework or emitted files: use the already installed TypeScript compiler.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInThisContext } from 'node:vm';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const modules = new Map();
function load(file) {
  if (modules.has(file)) return modules.get(file).exports;
  const compiled = { exports: {} };
  modules.set(file, compiled);
  const { outputText } = ts.transpileModule(readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }, fileName: file,
  });
  runInThisContext(`(function(require,module,exports){${outputText}\n})`, { filename: file })(
    (name) => load(resolve(dirname(file), `${name}.ts`)), compiled, compiled.exports,
  );
  return compiled.exports;
}

const { copilotMocks, staleActionErrorMock } = load(resolve(root, 'lib/copilot-mocks.ts'));
if (process.argv.includes('--fixtures')) {
  console.log(JSON.stringify(copilotMocks));
} else {
  const api = load(resolve(root, 'lib/copilot-api.ts'));
  const vm = load(resolve(root, 'lib/copilot-view-model.ts'));
  const { ApiError } = load(resolve(root, 'lib/api.ts'));
  const before = JSON.stringify(copilotMocks);
  assert.equal(vm.getCopilotStatusLabel('insufficient_data'), '확인 필요');
  assert.equal(vm.getSourceLocationLabel(copilotMocks.productEvidence.sources[0]), '조항 2 · 섹션 1 문단 3');
  assert.equal(vm.getSourceLocationLabel(copilotMocks.documentRag.sources[0]), '조항 2 · p.2, p.3');
  assert.equal(vm.getSourceLocationLabel({ ...copilotMocks.documentRag.sources[0], clause_label: null, source_locations: [], page: null }), '위치 정보 없음');
  const warnings = vm.getCopilotWarningItems(copilotMocks.documentRag);
  warnings.push('local edit');
  assert.equal(JSON.stringify(copilotMocks), before);
  const originalFetch = globalThis.fetch;
  const sent = [];
  try {
    globalThis.fetch = async (url, init) => {
      sent.push({ url, body: JSON.parse(init.body) });
      return new Response(JSON.stringify(copilotMocks.consentRequired), { status: 200 });
    };
    const request = { case_id: 'fixture', message: 'private message' };
    await api.sendCopilotMessage(request);
    assert.deepEqual(sent[0].body, request); // No copying message into public_document_question/opt-in.
    const proposal = copilotMocks.answerProposal.actions[0];
    const confirm = { confirmed: true, action: proposal };
    await api.confirmCopilotAction(confirm);
    assert.deepEqual(sent[1].body, confirm); // All expected context and input preserved.
    assert(sent[1].url.endsWith('/api/v1/copilot/actions/confirm'));
    let errorCalls = 0;
    globalThis.fetch = async () => {
      errorCalls++;
      return new Response(JSON.stringify(staleActionErrorMock), { status: 409 });
    };
    await assert.rejects(api.confirmCopilotAction(confirm), (error) => error instanceof ApiError
      && error.status === 409 && error.code === 'STALE_ACTION_CONTEXT' && error.message === staleActionErrorMock.error.message);
    assert.equal(errorCalls, 1); // A stale confirmation is never auto-retried.
    assert.equal(JSON.stringify(copilotMocks), before);
  } finally {
    globalThis.fetch = originalFetch;
  }

// Stateful checks reuse the existing compiler loader; no server or external data.
const { ConversationStore, validateSources } = load(resolve(root, 'lib/copilot-conversation.ts'));
let resolveFirst;
const transportRequests = [];
const store = new ConversationStore(async request => {
  transportRequests.push(request);
  return new Promise(resolve => { resolveFirst = resolve; });
});
const waiting = store.ask('case-a', '현재 결과', 'QUALIFICATION_SUMMARY');
assert.equal(store.get('case-a').busy, true);
assert.equal(store.get('case-b').turns.length, 0);
await store.ask('case-a', 'duplicate');
assert.equal(transportRequests.length, 1);
store.focus('case-a', 'R2');
resolveFirst(copilotMocks.eligible);
await waiting;
assert.equal(store.get('case-a').turns[0].response, undefined, 'Late reply cannot override new focus');
assert.equal(store.get('case-a').focus, 'R2');
assert.equal(store.get('case-b').focus, null);
assert.equal(transportRequests[0].allow_external_processing, undefined);
assert.equal(transportRequests[0].public_document_question, undefined);
assert.throws(() => validateSources({ ...copilotMocks.eligible, answer: '[S99]', sources: [] }));
console.log('Conversation isolation, duplicate reads, late response, privacy and invalid reference checks passed.');

  console.log('Copilot client/view-model checks passed; 11 response mocks + 1 error fixture. No network calls.');
}
