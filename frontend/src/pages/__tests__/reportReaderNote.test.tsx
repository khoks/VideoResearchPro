/**
 * T-8.8.4.4: the reading room shows the report's processing note.
 *
 * The compose step closes a section it could not get finished HTML for and
 * says so in the processing note (S-1.14.17). The note is the last paragraph
 * of the body; the page must show it above the text, as a labelled note, and
 * not again inside the body.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReportBody } from '../../types/report';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const report: { body: ReportBody | null } = { body: null };
vi.mock('../../hooks/useReport', () => ({
  useReportBody: () => ({ data: report.body, isLoading: false, error: null }),
}));
vi.mock('../../hooks/useJobs', () => ({ useJobVideos: () => ({ data: [] }) }));
vi.mock('../../hooks/useVideoFrames', () => ({ useCitationStills: () => undefined }));

import { ReportReaderPage } from '../ReportReaderPage';

const REPAIRED =
  'the "Key Facts" section was cut off mid-markup on both attempts to write it and was closed ' +
  'where it stopped, so it may end abruptly';

// What compose_report writes: sections, its Statistics block, then the note.
function body(note: string | null): ReportBody {
  return {
    job_id: 'j1',
    job_type: 'topic',
    title: 'Research Report: plotting',
    html:
      '<h2>Executive Summary</h2><p>The corpus treats charts as instruments of inference.</p>' +
      '<h2>Key Facts</h2><ul><li><strong>Seaborn</strong> wraps Matplotlib (</li></ul>' +
      '<div class="section"><h2>Statistics</h2><ul><li>Videos analyzed: 2</li></ul></div>' +
      (note
        ? '\n<p class="processing-note" style="color:#8a6d3b;border:1px solid #c9ba9b">' +
          `<strong>Processing note:</strong> ${note}.</p>`
        : ''),
    statistics: {
      video_count: 2,
      transcript_count: 2,
      total_words: 1200,
      total_minutes: 10,
      channel_breakdown: [],
    },
    generated_at: '2026-10-25 10:00',
  };
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/reports/j1']}>
          <Routes>
            <Route path="/reports/:jobId" element={<ReportReaderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
}

const squash = (s: string | null | undefined) => (s ?? '').replace(/\s+/g, ' ').trim();

describe('ReportReaderPage processing note', () => {
  it('shows the note above the body, labelled, and not inside the body', () => {
    report.body = body(REPAIRED);
    mount();

    const note = host.querySelector('[role="note"][aria-label="Processing note"]');
    expect(note).not.toBeNull();
    expect(squash(note!.textContent)).toBe(`Processing note: ${REPAIRED}.`);

    const reading = host.querySelector('.reader-body')!;
    expect(reading).not.toBeNull();
    // Before the text it qualifies...
    expect(note!.compareDocumentPosition(reading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // ...and only once.
    expect(reading.textContent).not.toContain('Processing note');
    expect(reading.textContent).not.toContain('cut off mid-markup');
    // The sections themselves still render.
    expect([...reading.querySelectorAll('h2')].map((h) => h.textContent)).toEqual([
      'Executive Summary',
      'Key Facts',
      'Statistics',
    ]);
  });

  it('shows no note when the report has none', () => {
    report.body = body(null);
    mount();
    expect(host.querySelector('[aria-label="Processing note"]')).toBeNull();
    expect(host.querySelector('.reader-body h2')?.textContent).toBe('Executive Summary');
  });
});
