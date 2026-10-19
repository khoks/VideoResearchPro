# API fixtures for the mobile device tests

`tests/mobile.spec.ts` serves these through `page.route('**/api/v1/**')`, so the device-emulation tests need only the Vite dev server: no backend, database, Redis or LLM.

| File | Source |
|---|---|
| `health.json`, `auth-me.json`, `shelves.json`, `job.json`, `job-videos.json`, `report-body.json`, `knowledge.json` | Captured on 2026-10-19 from a scratch copy of the dev database, as the `tier-test@example.com` test account, through the real routes. The report is job `1c222ce6…` (the "pratidhvani smoke test" run over three public YouTube videos). The knowledge report is the stored artifact for the public video `4_2j5wgt_ds`. |
| `job-qa.json` | **Synthetic.** Written by hand about the same three public videos, because the test account has no Q&A history and the user's own exchanges do not belong in a public repository. Every answer starts with "Synthetic fixture answer". |

Routes the pages call that have no file here are answered with an empty list (`/notes`, `/library/qa`). Any other unmatched `/api/v1/` request fails the test, so a page that starts calling something new is noticed.

To refresh the captured files, re-run the capture against a backend that has the reference job, and check the diff for anything account-specific before committing.
