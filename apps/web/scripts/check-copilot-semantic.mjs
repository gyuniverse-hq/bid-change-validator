// Verify that semantic routing consent is explicit at the HTTP boundary.
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
    name => load(resolve(dirname(file), `${name}.ts`)), compiled, compiled.exports,
  );
  return compiled.exports;
}

const { ConversationStore } = load(resolve(root, 'lib/copilot-conversation.ts'));
const { copilotMocks: m } = load(resolve(root, 'lib/copilot-mocks.ts'));
const id = m.eligible.product_state.provenance.case_id;
const calls = [];
const originalFetch = globalThis.fetch;

try {
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init, body: JSON.parse(String(init.body)) });
    return {
      ok: true,
      status: 200,
      json: async () => structuredClone(m.eligible),
    };
  };

  const store = new ConversationStore();
  await store.ask(id, '회사 허가와 제품 허가를 구분해줘', undefined, 'QUALIFICATION', false);
  await store.ask(id, '평가점수와 필수 참가요건을 구분해줘', undefined, 'QUALIFICATION', true);

  assert.equal(calls.length, 2);
  assert.equal(calls[0].url.endsWith('/api/v1/copilot/chat'), true);
  assert.equal(calls[0].init.headers['X-Copilot-Semantic-Processing'], undefined);
  assert.equal(calls[1].init.headers['X-Copilot-Semantic-Processing'], 'true');
  assert.equal('semantic_processing' in calls[0].body, false);
  assert.equal('semantic_processing' in calls[1].body, false);
  assert.equal(calls[1].body.message, '평가점수와 필수 참가요건을 구분해줘');
  assert.equal(calls[1].body.user_input, undefined);

  console.log('PASS semantic routing is opt-in by header; consent flag is not serialized into product payload');
} finally {
  globalThis.fetch = originalFetch;
}
