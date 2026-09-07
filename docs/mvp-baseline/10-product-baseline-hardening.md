# Product Baseline Hardening

## Product definition

The Product Baseline is complete only when the following flow works with traceable data and conservative abstention:

```text
Company Profile
→ G2B notice discovery
→ source document parsing
→ Qualification Requirement extraction
→ Canonical Mapping
→ Evidence provenance
→ deterministic company comparison
→ SATISFIED / UNSATISFIED / UNKNOWN
→ ASKABLE UNKNOWN only → USER_ANSWER
→ affected Requirement partial re-judgment
→ changed notice diff
→ affected-only revalidation
```

LLM/RAG is responsible for document understanding, extraction and evidence grounding. Final qualification status is produced by deterministic rules. Unsupported or ambiguous source clauses must remain diagnostics/UNKNOWN rather than being forced into a supported canonical type.

## Golden Product Scenario

We keep two complementary Golden scenarios.

### G0 — deterministic regression fixture

`apps/api/tests/test_mvp_golden_e2e.py` is the executable regression contract.

It covers:

- company profile facts: region / staff / performance
- baseline Requirement judgment
- one missing registration fact → UNKNOWN
- Ask-back answer with `apply_to_profile=false`
- `basis_type=USER_ANSWER`
- partial re-judgment
- changed notice Requirement Diff
- MODIFIED-only affected revalidation
- unchanged USER_ANSWER preservation across revalidation

This fixture is synthetic by design so CI is deterministic.

### G1 — actual collected notice reality check

The current local product validation used notice `R26BK01687395` (가덕도신공항 여객터미널 및 부대건물 설계단계 건설사업관리용역) as an extraction/evidence reality check.

Observed before hardening:

- analysis status: `PARTIAL`
- canonical Requirements: 3
- Evidence: 3
- all three mapped as `REGISTRATION_CERTIFICATION`
- multiple `UNMAPPED_REQUIREMENT` diagnostics
- initial judgment: UNKNOWN 3
- Ask-back could turn the three complex clauses into USER_ANSWER judgments

This is intentionally retained as a failure/reality-check case. It is **not** the changed-notice Golden Case because the observed Case had only the first notice version.

### G2 — actual changed-notice Golden candidate

Run:

```bash
python -m apps.api.app.scripts.select_golden_product_scenario
```

The selector ranks actual collected notices with 2+ versions, extracted documents and meaningful change fields. Select one high-ranked notice and freeze its notice number in this document after local verification.

Acceptance criteria for the final actual changed-notice Golden Case:

1. 2+ actual `NoticeVersion` rows.
2. Current and baseline source documents are downloaded and parsed.
3. At least one supported canonical Requirement is unchanged.
4. At least one canonical Requirement is MODIFIED or ADDED.
5. Requirement Diff revalidates only affected keys.
6. Evidence location remains traceable to each source version.

## P0 hardening

### Requirement Extraction / Mapping

- Do not reduce joint-contract, representative-conflict, legal exception, negated or other composite clauses to a simple registration/certification fact.
- Prefer `기타요건 → UNMAPPED_REQUIREMENT` over an unsafe canonical mapping.
- Preserve raw source semantics verbatim.
- Expand fallback chunk recall while retaining source-grounding validation.

### Askability Guardrail

`UNKNOWN != ASKABLE`.

ASKABLE is restricted to one user-known fact that can deterministically resolve one canonical Requirement. Complex legal/procedural clauses remain `NOT_ASKABLE` and must be reviewed in Evidence.

Backend enforcement is mandatory: even if a client manually posts an answer for a `NOT_ASKABLE` Requirement, the API must reject it.

### Question semantic preservation

An askable question includes both a readable canonical prompt and the original raw source condition. A short canonical value must never silently replace source semantics.

### USER_ANSWER provenance

Policy A remains the Product Baseline contract:

```text
USER_ANSWER
→ current Case judgment basis only
→ partial re-judgment
→ Company Profile unchanged
→ apply_to_profile=false
```

UI must distinguish `PROFILE` from `USER_ANSWER`; a row must not look as if an empty profile value magically produced SATISFIED/UNSATISFIED.

### Regression

The existing Golden E2E test is the baseline regression for Ask-back partial re-judgment. New Askability unit tests cover unsafe clause classes and question semantic preservation.

## P1 hardening

1. Actual changed-notice Golden Case selected via the selector above.
2. First notice only → no false diff table; show a no-change-history empty state.
3. Profile completeness uses one seven-area definition everywhere:
   - INDUSTRY
   - REGION
   - COMPANY_SIZE
   - STAFF
   - PERFORMANCE_COUNT
   - PERFORMANCE_AMOUNT
   - REGISTRATION_CERTIFICATION
4. Restore Figma 02 information architecture: notice summary / qualification / submission documents / risky-unmapped clauses / evidence / actions.
5. Expose create/update UX for company performances and certifications using the already implemented Backend CRUD endpoints.

## P1–P2 notice matching

Do not call all unreviewed notices "matched". Product matching will be staged:

```text
Stage 1 cheap candidate filter
→ existing structured metadata / cached analyses
Stage 2 qualification analysis only for candidates
→ canonical Requirements + Evidence
Stage 3 deterministic company comparison
→ eligible / insufficient_data / ineligible
```

Until this is implemented, UI copy must distinguish `조회된 공고` from `회사 조건으로 판정된 공고`.

## P2 Evaluation Contract

Evaluation does not predict a score. A dedicated contract should represent source-grounded evaluation criteria independently of qualification Requirements:

```text
EvaluationCriterion
- criterion_key
- title
- raw
- max_score (source value only, nullable)
- evaluation_method
- response_fields
- evidence_keys
```

The Product Baseline may display source criteria and company response facts. Score prediction remains out of scope.

## P2 USER_ANSWER → Profile Promotion (Policy B)

Deferred enhancement after Product Baseline stabilization.

Promotion requires a Requirement-type-specific workflow, enough structured fields for the destination Company schema, provenance, user confirmation and evidence handling. A bare yes/no answer must never silently mutate the reusable Company Profile.
