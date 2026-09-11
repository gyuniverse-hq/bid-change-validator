# Copilot v1 — Pre-Copilot baseline / frontend design integration

## Fixed sources
- Product: develop `40de1a3` (#107/#112/#114), same source tree as main release `02033a3` (#116).
- Copilot implementation: `4bc6632` (A–D). Original working directories and exports are not modified.
- Designer: 황수빈 Notion “챗봇 화면 설계”, page `3d7e94b44d078039b3f1fffa76d7046b`.
- Supplied Figma CSS: 7 states. The actual Figma MCP canvas could not be read due to its tool-call quota. The neutral circular mascot is reconstructed from these CSS specifications, not claimed to be the exported asset.

## Product preservation
Three-way source integration preserves baseline auth routers, DB migrations and opt-in master-code fixture; #107 skip/unskip and Korean change labels; #112/#114 out-of-judgment scope, missing raw copy and resolved-Evidence-only buttons. Copilot controller, explicit confirmations and client-side navigation remain. No Core judgment or external-model policy change.

## Added boundaries
- Existing HttpOnly session cookies are shared only with the configured API origin. No token storage or new auth/tenant implementation. Cross-site cookie/CORS deployment policy and user/case authorization remain separate gates.
- Only the backend's known pre-handler 401 codes are classified as AUTH_REQUIRED. Unknown 401, network timeout and 5xx retain OUTCOME_UNKNOWN; no automatic write retry.
- Full review and Copilot actions share an in-tab mutation lock. This is not a distributed lock.
- Workspace refresh failure preserves the last loaded data, labels it stale, disables new actions there and keeps the action card accessible.
- Revalidation summary must match case, baseline/current analysis and result judgment before being displayed as current.
- Analysis scope is derived from the exact judged analysis. NOTICE_FACT has resolved Evidence only; dropped candidates have no invented keys/links. Diagnostic details are not copied into explanation. The saved overall judgment remains unchanged.
- Out-of-scope reasons are not ordinal/action targets. Source refs remain response-global.

## Design implementation map
| Source requirement | Implementation |
|---|---|
| 400 × 720 reference, 24/20 radii, 20 padding, 14 gap | responsive common panel CSS |
| 20 / 64 neutral mascot | CSS circle and eyes, fixed expression |
| Gothic A1 and common tokens | existing font variable and product palette |
| Status / version | labelled last-read Backend state, no fixed mock status |
| Empty / no judgment / loading / answer / changed / insufficient evidence / error | shared renderer with explicit display states |
| EvidenceChip | response-validated source label / document location and 04 link |
| 03 / 06 detail | panel summaries; shared controller explicit execution in detail |
| Mobile Drawer | native modal dialog below 1024px, no new chat store |
| Error retry | replays the failed read intent/context, never confirm |

Intentional differences: layout memory instead of localStorage/server history; actual partial/no-judgment state instead of `analysis != SUCCEEDED`; evidence absence is evaluated only for evidence-required responses. Existing design-token warning palette is reused; generic errors use a distinct error surface.

## Verification and reproduction
Run the repository's Copilot integration workflow. `scripts/ci_copilot_integration.sh` refuses a missing or non-CI/non-loopback/non-`copilot_ci` DB target before tests.

The workflow runs migrations, the full Backend suite, the existing fixed evaluation, TypeScript, three client/state scripts, changed-file lint, a production build and actual app rendering in Chromium with intercepted synthetic API fixtures. Screenshots cover all seven display states and a mobile Drawer. The browser test explicitly labels itself **actual UI + synthetic API**, not real-DB browser E2E. DB behavior is separately tested by the actual PostgreSQL suite including confirm/replay/rollback tests.

Do not reuse old “605 passed” or “100% independent holdout” claims for this source tree. Read the exact run's logs and JUnit artifact. The fixed evaluation was previously exposed to implementation and remains regression, not independent holdout. Existing unrelated repo-wide lint debt is logged separately. Human usability / pixel-perfect comparison / authenticated multi-user deployment tests are not represented by this automated check.

## Remaining gates
- User/case authorization, cross-site deployment cookie policy and login UX are not created here.
- Figma asset-owner visual signoff and human comprehension evaluation remain outstanding.
- Layout-memory recovery does not survive refresh/tab close; OUTCOME_UNKNOWN is never unlocked by a read alone.
- Real-data extraction quality, registration/profile mapping and empty attachments remain baseline follow-ups.
