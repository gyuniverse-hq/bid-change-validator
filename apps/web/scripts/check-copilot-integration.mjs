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


const { ActionController, currentRevalidation } = load(resolve(root, 'lib/copilot-actions.ts'));
const { ConversationStore } = load(resolve(root, 'lib/copilot-conversation.ts'));
const { ApiError, apiFetch } = load(resolve(root, 'lib/api.ts'));
const { copilotMocks: m } = load(resolve(root, 'lib/copilot-mocks.ts'));
const action = m.answerProposal.actions[0], id = action.expected.case_id;
for (const [code, stage] of [['AUTHENTICATION_REQUIRED','AUTH_REQUIRED'],['INVALID_SESSION','AUTH_REQUIRED'],['UNKNOWN_PROXY','OUTCOME_UNKNOWN']]) {
  let writes=0;
  const c = new ActionController(async()=>m.eligible,async()=>{writes++;throw new ApiError('auth',401,code);});
  c.adopt(id,action);await c.confirm(id,true);assert.equal(c.get(id).stage,stage);
  await c.confirm(id,true);assert.equal(writes,1);
  c.cancel(id);assert.equal(c.get(id).stage,stage==='AUTH_REQUIRED'?'IDLE':'OUTCOME_UNKNOWN');
}
const c=new ActionController();c.adopt(id,action);assert(c.acquireReview(id));
assert.equal(c.get(id).proposal,null);assert.equal(c.acquireReview(id),false);
c.adopt(id,action);assert.equal(c.get(id).proposal,null);c.releaseReview(id);c.adopt(id,action);assert(c.get(id).proposal);
const result={preflight_case_id:id,baseline_analysis_run_id:'a1',current_analysis_run_id:'a2',result_judgment_run_id:'j2',revalidated_keys:[]};
assert.equal(currentRevalidation(result,{caseId:id,baselineAnalysisId:'a1',currentAnalysisId:'a2',judgmentId:'j2'}),result);
for(const patch of [{caseId:'other'},{baselineAnalysisId:'other'},{currentAnalysisId:'a3'},{judgmentId:'j3'}])
 assert.equal(currentRevalidation(result,{caseId:id,baselineAnalysisId:'a1',currentAnalysisId:'a2',judgmentId:'j2',...patch}),null);
let tries=0;const requests=[];const store=new ConversationStore(async request=>{requests.push(request);if(!tries++)throw Error('offline');return m.eligible;});
await store.ask(id,'변경된 요건 보여줘','CHANGED_NOTICE','CHANGES');await store.retry(id);
assert.equal(requests[1].message,requests[0].message);assert.equal(requests[1].intent,'CHANGED_NOTICE');
assert.notEqual(requests[1].conversation_context.request_id,requests[0].conversation_context.request_id);
assert.deepEqual(requests[1].conversation_context.last_read_receipt,requests[0].conversation_context.last_read_receipt);
const fetches=[],originalFetch=globalThis.fetch;
try{globalThis.fetch=async(url,init)=>{fetches.push([url,init]);return {};};
 await apiFetch('/api/v1/copilot/chat',{method:'POST',body:'{}'});
 await apiFetch('https://unrelated.invalid/document');
 assert.equal(fetches[0][1].credentials,'include');assert.equal(fetches[1][1].credentials,'omit');
 assert.equal(fetches.length,2);
}finally{globalThis.fetch=originalFetch;}
console.log('PASS 401 classification, shared review lock, result provenance, exact read retry, API-origin cookie boundary');
