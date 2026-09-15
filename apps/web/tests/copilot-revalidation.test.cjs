/* oxlint-disable typescript/no-require-imports -- Standalone Node test runner. */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../lib/copilot-actions.ts'), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const context = {exports:{}, require:()=>({})};
vm.runInNewContext(compiled, context);
const {currentRevalidation} = context.exports;
test('saved comparison is current only for the same case, both analyses and resulting judgment', () => {
  const saved={preflight_case_id:'case',baseline_analysis_run_id:'a1',current_analysis_run_id:'a2',result_judgment_run_id:'j2',revalidated_keys:[]};
  const current={caseId:'case',baselineAnalysisId:'a1',currentAnalysisId:'a2',judgmentId:'j2'};
  assert.equal(currentRevalidation(saved,current),saved);
  for(const field of Object.keys(current)) assert.equal(currentRevalidation(saved,{...current,[field]:'changed'}),null);
  assert.equal(currentRevalidation(saved,{caseId:'case'}),null);
  assert.equal(currentRevalidation(null,current),null);
});
