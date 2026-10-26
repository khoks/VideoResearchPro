# API fixtures for the mobile device tests

`tests/mobile.spec.ts` serves these through `page.route('**/api/v1/**')`, so the device-emulation tests need only the Vite dev server: no backend, database, Redis or LLM.

| File | Source |
|---|---|
| `health.json`, `auth-me.json`, `shelves.json`, `job.json`, `job-videos.json`, `report-body.json`, `knowledge.json` | Captured on 2026-10-19 from a scratch copy of the dev database, as the `tier-test@example.com` test account, through the real routes. The report is job `1c222ce6…` (the "pratidhvani smoke test" run over three public YouTube videos). The knowledge report is the stored artifact for the public video `4_2j5wgt_ds`. |
| `job-qa.json` | **Synthetic.** Written by hand about the same three public videos, because the test account has no Q&A history and the user's own exchanges do not belong in a public repository. Every answer starts with "Synthetic fixture answer". |
| `graph.json` | **Synthetic.** A hand-made `GET /library/graph` response for `tests/graph.spec.ts`: nine sources on one channel, three topics, one question. Source 9 links only to its channel, so the single-link rule leaves 13 nodes drawn. |

Routes the pages call that have no file here are answered inline in the spec: an empty notes page, an onboarded account (`/auth/me/onboarding`), no library rows, no suggestions, no citation channels (`/library/video-channels`), no notifications for the bell (`/notifications`) and no captured frames for the run's three videos (`/videos/{id}/frames`), the state the baselines were recorded in. Any other unmatched `/api/v1/` request fails the test, so a page that starts calling something new is noticed. The bell and the frames calls arrived after the baselines (S-8.3.3 and S-1.18.2) and failed every mobile test until their answers were added here; CI now runs the suite on every PR ([testing.md §5.4](../../../../docs/testing.md#54-ci)), so the next such call is caught on its own PR.

To refresh the captured files, re-run the capture against a backend that has the reference job, and check the diff for anything account-specific before committing.
