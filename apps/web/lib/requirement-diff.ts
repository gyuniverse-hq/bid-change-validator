import type { QualificationRequirement } from './copilot-api';

const FIELDS = ['type', 'operator', 'value', 'unit', 'period_months', 'required',
  'requirement_role', 'condition_complexity', 'group_operator'] as const;

function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.entries(value)
    .sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]);
  return value;
}

function conditionScope(scope: Record<string, unknown> | null | undefined) {
  const result = { ...scope };
  // Only known provenance fields are omitted from this display classification.
  // Operator, code, exceptions, group relation and every unknown scope key stay.
  for (const [key, omitted] of [['source_contract', 'raw_sha256'], ['source_group', 'workbook_sha256'],
    ['source_group', 'source_fingerprint']]) {
    const value = result[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const copy = { ...value } as Record<string, unknown>;
      delete copy[omitted]; result[key] = copy;
    }
  }
  return canonical(result);
}

/** Display only: backend revalidation still checks the complete original basis. */
export function sameStructuredValue(before: QualificationRequirement | null, after: QualificationRequirement | null) {
  return !!before && !!after && FIELDS.every(field => before[field] === after[field])
    && JSON.stringify(conditionScope(before.scope)) === JSON.stringify(conditionScope(after.scope));
}
