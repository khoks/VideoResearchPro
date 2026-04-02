# VideoResearchPro — UI Design

## Design Language

- **Color palette**: Primary gradient `#667eea → #764ba2` (purple-blue), background `#f1f5f9` (light slate), cards `#fff`, text `#1e293b` (dark slate)
- **Typography**: System font stack (`-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, ...`)
- **Border radius**: `8px` for inputs/buttons, `12px` for cards
- **Shadows**: Subtle `0 1px 3px rgba(0,0,0,0.08)` on cards
- **Styling approach**: Inline `style={{}}` objects on React components (no CSS modules, no styled-components)

## Layout

```
┌──────────────────────────────────────────────────────┐
│  [VideoResearchPro]    [Submit Job]  [Jobs]          │  ← Gradient header
├──────────────────────────────────────────────────────┤
│                                                      │
│   ┌──────────────────────────────────────────────┐   │
│   │                                              │   │  ← Max-width 1200px
│   │              Page Content                    │   │     centered container
│   │              (<Outlet/>)                     │   │
│   │                                              │   │
│   └──────────────────────────────────────────────┘   │
│                                                      │
└──────────────────────────────────────────────────────┘
```

- **Header**: Fixed gradient banner with app title (clickable → home) and two tab buttons
- **Tab buttons**: Translucent white background when active (`rgba(255,255,255,0.2)`), transparent when inactive
- **Content area**: Max-width 1200px, centered, 1.5rem padding

## Pages

### Submit Job Page (`/submit`)

```
┌──────────────────────────────────────────┐
│  Create Research Job                     │
│                                          │
│  Job Type:  [● Topic] [○ Channel]        │  ← Radio toggle
│                                          │
│  ┌─ Topic Mode ────────────────────────┐ │
│  │  Topic: [________________________]  │ │
│  │  Search Instructions:               │ │
│  │  [______________________________]   │ │
│  │  [______________________________]   │ │
│  │  Number of Videos: [10___]          │ │
│  │  Min Duration (min): [____]         │ │
│  │  Max Duration (min): [____]         │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  ┌─ Channel Mode ──────────────────────┐ │
│  │  Channel URLs (one per line):       │ │
│  │  [______________________________]   │ │
│  │  [______________________________]   │ │
│  │  Videos per Channel: [10___]        │ │
│  │  Min Duration (min): [____]         │ │
│  │  Max Duration (min): [____]         │ │
│  └─────────────────────────────────────┘ │
│                                          │
│  [Submit Job]                            │  ← Gradient button
└──────────────────────────────────────────┘
```

- White card with rounded corners
- Form fields toggle visibility based on job type selection
- Submit navigates to the new job's detail page on success
- Disabled state during submission with loading indicator

### Jobs List Page (`/jobs`)

```
┌──────────────────────────────────────────┐
│  Research Jobs                           │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Topic: "AI Safety"  [Completed]   │  │  ← Clickable job card
│  │  ██████████████████████████ 100%   │  │  ← Colored progress bar
│  │  Report generated       2 hours ago│  │
│  │                         [Delete]   │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  Channel Collection  [Extracting]  │  │
│  │  ████████████░░░░░░░░░░░░░ 45%    │  │
│  │  Fetching transcripts... just now  │  │
│  │                         [Cancel]   │  │
│  └────────────────────────────────────┘  │
│                                          │
│  (empty state: "No jobs yet...")         │
└──────────────────────────────────────────┘
```

- Each card is a clickable row navigating to job detail
- Status badge: colored pill (green=completed, blue=running, yellow=awaiting, red=failed/cancelled)
- Progress bar: colored by status, animated
- Action buttons: Cancel (for active jobs), Delete (for terminal jobs) — click stops propagation
- Active jobs auto-update via WebSocket (no polling)

### Job Detail Page (`/jobs/:jobId`)

```
┌──────────────────────────────────────────┐
│  ← Back to Jobs                          │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │  "AI Safety Research"  [Completed] │  │  ← Job header card
│  │  Created Mar 25, 2026 | topic job  │  │
│  │  ████████████████████████████ 100% │  │
│  │  Report generated (100%) [Cancel/Delete]│ ← Cancel for active, Delete for terminal
│  │  Error: ... (if any, red text)     │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌─ Video Approval (awaiting_approval)─┐ │
│  │  Review Videos (8/10 selected)      │ │
│  │  Deselect any videos...             │ │
│  │  [✓] Video Title 1                 │  │
│  │      Channel Name | 12:34          │  │
│  │  [✓] Video Title 2                 │  │
│  │      Channel Name | 5:67           │  │
│  │  [ ] Video Title 3 (deselected)    │  │
│  │  [Approve & Continue (8 videos)]   │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌─ Videos (non-approval states) ──────┐ │
│  │  Videos (10)                        │ │
│  │  Video Title 1 (linked)             │ │
│  │    Channel | 12:34 | fetched        │ │
│  │  Video Title 2 (linked)             │ │
│  │    Channel | 5:67 | fetched         │ │
│  └────────────────────────────────────┘  │
│                                          │
│  [View Report]                           │  ← Only if has_report
│                                          │
│  ┌─ Ask Questions (completed only) ────┐ │
│  │  [________________________] [Ask]   │ │  ← Both disabled while processing
│  │  [spinner] Analyzing transcripts... │ │  ← Loading indicator while pending
│  │                                     │ │
│  │  Q: What are the main findings?     │ │
│  │  A: Based on the research...        │ │
│  │  References:                        │ │
│  │    Video Title by Channel at 3:45   │ │
│  └─────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

Sections appear conditionally:
- **Video Approval**: Only when status = `awaiting_approval`. Checkbox list, all selected by default.
- **Video List**: When status != `awaiting_approval` and videos exist. Read-only list with links.
- **View Report button**: Only when `has_report = true`.
- **Q&A Panel**: Only when status = `completed`.

### Report Modal (full-page overlay)

```
┌──────────────────────────────────────────────────────┐
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
│░░┌──────────────────────────────────────────────[X]░░│
│░░│                                                 │░░│
│░░│           HTML Report (iframe)                  │░░│  ← 90vw x 90vh
│░░│           /api/v1/jobs/{id}/report              │░░│     white card
│░░│                                                 │░░│
│░░│  ┌─────────────────────────────────────────┐    │░░│
│░░│  │  Research Report: AI Safety             │    │░░│
│░░│  │  Stats Grid | Findings | References     │    │░░│
│░░│  └─────────────────────────────────────────┘    │░░│
│░░│                                                 │░░│
│░░└─────────────────────────────────────────────────┘░░│
│░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│
└──────────────────────────────────────────────────────┘
  ░ = dark overlay (rgba(0,0,0,0.5)), click to close
```

- Fixed position overlay covers entire viewport
- White card: 90vw x 90vh, border-radius 12px
- Close button: red circle in top-right corner (position absolute)
- Content: iframe pointing to the report API endpoint
- Click on backdrop (dark overlay) dismisses modal

## Components

### StatusBadge
Colored pill showing job status text:
- **pending/searching**: blue (`#3b82f6`)
- **awaiting_approval**: yellow/amber (`#f59e0b`)
- **extracting/building_rag/generating_report**: blue (`#3b82f6`)
- **completed**: green (`#22c55e`)
- **cancelled**: gray (`#94a3b8`)
- **failed**: red (`#ef4444`)

Style: inline-block, padding `0.2rem 0.6rem`, border-radius 12px, font-size 0.75rem, font-weight 600, white text on colored background.

### ProgressBar
Horizontal bar showing completion percentage:
- Container: full width, height 8px, background `#e2e8f0`, border-radius 4px
- Fill: animated width transition (0.3s ease), color varies by status
- Colors match StatusBadge scheme

### LoadingSpinner
CSS animation spinner:
- Circular border spinner using `@keyframes spin`
- Configurable size prop
- Color: `#667eea` (primary blue)

## Interaction Patterns

### Job Creation Flow
1. User selects job type (topic/channel) on Submit page
2. Fills form fields, clicks Submit
3. Button shows loading state while API call processes
4. On success: navigates to `/jobs/{newJobId}` (detail page)
5. WebSocket auto-subscribes to the new job's progress

### Job Monitoring Flow
1. Jobs list page shows all jobs with real-time progress
2. Active jobs update progress bars and messages via WebSocket
3. Click any job card → navigate to detail page
4. Detail page subscribes to that job's WebSocket updates

### Approval Flow
1. Job reaches `awaiting_approval` → WebSocket triggers `jobVideos` query invalidation
2. Video approval list auto-populates with checkboxes (no manual refresh needed)
3. All videos pre-selected; user deselects unwanted ones
4. Click "Approve & Continue" → PUT /approve with selected IDs
5. Job resumes: status transitions through extracting → building_rag → generating_report → completed

### Q&A Flow
1. Job is `completed` → Q&A section appears on detail page
2. User types question in input, clicks Ask (or Enter)
3. Input field and Ask button are **disabled** while processing
4. Loading spinner with "Analyzing transcripts and generating answer..." message appears
5. Backend runs 4-step Q&A pipeline: retrieve → refine context → answer → extract references
6. Answer appears with references (clickable YouTube timestamp links)
7. Input re-enables; history persists and displays below the input

### Job Deletion
1. Completed/cancelled/failed jobs show a **Delete** button on both the jobs list and job detail page
2. Delete removes: DB records (job, videos, Q&A exchanges), ChromaDB collection, HTML report file
3. On detail page, delete navigates back to jobs list
