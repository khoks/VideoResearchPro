# M10 — Onboarding wizard and empty states: plan

**Board:** [E-8.10](../initiatives.md#e-810--onboarding-wizard-and-empty-states-m10) · **Roadmap:** [M10](../feature-roadmap.md#m10--onboarding-wizard--empty-state-polish-) · **Research date:** 2026-10-19 · **Status:** recommendation.

## Problem

A new account lands on the submit page with nothing explained and nothing to show. The roadmap asks for a first-run flow (pick channels, run a first job, see the result) and empty-state polish, calling it high-leverage for SaaS conversion later; it is useful for self-hosters now.

## Verified current state (2026-10-18)

- `users` has no onboarding column; no `/welcome` route; `/` redirects to `/submit`.
- Channel search and subscribe exist (`LibraryPage` Channels tab, `POST /channels/{id}/subscribe`); job creation exists; progress arrives over the WebSocket; the `EmptyState` primitive exists in `components/primitives/EmptyState.tsx` and is used on some pages.
- Ingest is slow by design: the transcript throttle is 3 s per video with Whisper fallback, so a 50-video first job can take many minutes and may pause at `awaiting_approval`.
- `audit_log` exists (E-5.4) and already records events such as `tier_changed`.

## Chosen approach

- **A task-flow wizard page, not an overlay tour.** NN/g's position is that overlay walkthroughs are "dramatically overused" and skipped; the specified flow *is* a stepper with real actions. A plain `Stepper` with inline styles and the existing mutations needs no library. Shepherd.js is AGPL-3.0 from version 14 and Intro.js is AGPL-3.0 with a paid licence; `driver.js` (MIT, 7.7 kB) exists if coach marks are ever wanted.
- **Three steps at `/welcome`**: (1) pick three to five channels through the existing search and subscribe; (2) start a **deliberately tiny** first job (three to five videos from one channel) from an M6 starter template, so the throttle does not turn "see the result" into a half-hour wait, with expected time shown and the option to leave and return; (3) progress, then "Read it" into the M8 reader. Skip is always visible; the wizard is resumable and reopenable from the sidebar.
- **State on the server**: `users.onboarded_at` and `users.onboarding_state_json` (`{step, choices, completed_at, dismissed_tips}`) through `PATCH /auth/me/onboarding`, because the stated goal is multi-device and because the Celery task that finishes the first job can flip the state. `localStorage` only for cosmetic per-device things.
- **Activation events** in `audit_log`: `onboarding_started`, `first_job_created`, `first_report_opened`, `first_cited_answer`. The natural activation milestone is "first report opened" (or first cited answer) with time-to-first-report as the secondary metric; survey medians for SaaS activation sit around 30 %.
- **Empty-state audit** (S-8.10.2) against NN/g and Atlassian guidance: every empty container states system status (empty versus loading versus error, never "no records" while loading), a learning cue, and one direct action in place; header, description, one primary action, optional illustration; editorial voice from `branding.md`. Pages: jobs, library, channels, Q&A history, exports, author, echo, shelves, notes, saved searches. A first-run checklist card on the jobs page until three milestones are hit, persistent and dismissible (the pattern comparable products use instead of modals).
- WCAG 2.2 SC 3.3.7 (redundant entry): the wizard never re-asks what the user already entered.

## Alternatives rejected

| Option | Why not |
|---|---|
| `react-joyride` / Shepherd / Intro.js overlay tour | Overlays underperform task flows; Shepherd ≥ 14 and Intro.js are AGPL-3.0. |
| A full-size first job | Minutes of waiting at the one moment the user's attention is highest. |
| `localStorage` onboarding state | Not multi-device; lost on browser reset; invisible to the worker. |
| A modal checklist | Interrupting; the sidebar card is dismissible and findable. |

## Schema deltas

`users.onboarded_at DATETIME NULL`, `users.onboarding_state_json TEXT NULL`.

## API deltas

`PATCH /api/v1/auth/me/onboarding`; `GET /auth/me` includes `onboarded_at` and the state.

## Modules touched

`models/user.py`, one Alembic revision, `routers/auth.py`, `services/audit_service.py` (event names), `tasks/job_tasks.py` (flip state on first completion), `frontend/src/pages/WelcomePage.tsx` and `components/onboarding/{Stepper,ChecklistCard}.tsx` (new), `routes/index.tsx` (redirect while incomplete), `layouts/AppLayout.tsx` (reopen link), every page's empty state, `components/primitives/EmptyState.tsx`.

## Risks

- **Rate limits and approval**: the first job must tolerate `awaiting_approval` (topic jobs pause for approval) or use a channel job which does not; recommended: a channel job of five videos. *Correction 2026-10-19 (S-8.10.1): channel jobs pause too (`job_tasks` channel fetch ends at `awaiting_approval`), so the shipped wizard approves inline in step 3.*
- **Redirect loops**: the "redirect from `/` while incomplete" rule must exempt `/welcome`, auth pages and the skip path.
- **Copy** is editorial work; the audit is as much writing as code.

## Test strategy

- Router: PATCH state, isolation, `onboarded_at` set on completion; the worker flips the first-job milestone.
- Frontend: type-check; Playwright flow new account → wizard → skip; new account → three steps → report; redirect logic.
- Empty states: a snapshot per page at zero data.

## First PR (S-8.10.1)

The two columns, the PATCH endpoint, the `/welcome` stepper with the three steps, redirect and skip, the audit events, tests. Depends on M6's starter templates for step 2 (or, if sequenced first, seeds one template inline).

## Open questions

1. Channel job (no approval pause) or topic job (shows the curation flow, pauses) for the first run?
2. Should onboarding be shown to existing accounts once (with "skip") or only to accounts created after it ships?

## Sources (fetched 2026-10-19)

npm metadata for `react-joyride`, `driver.js`, `@reactour/tour`, `shepherd.js` (licence history), `intro.js` (licence page); NN/g "Onboarding Tutorials vs. Contextual Help" (2023) and "Empty-State Interface Design" (2021); Atlassian Design System empty-state usage; Lenny's Newsletter activation survey (2022); WCAG 2.2 SC 3.3.7. Full URLs with per-claim verification tags are in the raw research notes under [`research/`](research/) (`l2-author-studio.md`, `l3-echo-connectors.md`, `l3-echo-personality.md`, `m1-m6.md`, `m7-m12.md`).
