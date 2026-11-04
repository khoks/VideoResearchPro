/**
 * S-8.6.3: "Job parameters" names a run's publish window, so a reader can see
 * why a run leaned recent, and shows nothing when the run set none.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import { JobParamsCard } from '../JobDetailPage';
import type { Job } from '../../types/job';

const JOB: Job = {
  id: 'job-1',
  job_type: 'topic',
  status: 'completed',
  created_at: '2026-11-04T00:00:00Z',
  updated_at: '2026-11-04T00:00:00Z',
  completed_at: null,
  topic: 'tariffs',
  search_instructions: null,
  num_videos: 10,
  min_duration_minutes: null,
  max_duration_minutes: null,
  channel_type_filters: null,
  preferred_channels: null,
  channel_list: null,
  videos_per_channel: null,
  output_length: null,
  visual_analysis: false,
  template_id: null,
  template_version: null,
  progress_pct: 100,
  progress_message: null,
  error_message: null,
  video_count: 10,
  transcript_count: 10,
  has_report: true,
};

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

describe('Job parameters: publish window', () => {
  it('names the window a run set', () => {
    act(() => root.render(<JobParamsCard job={{ ...JOB, published_after_days: 30 }} />));
    expect(host.textContent).toContain('Prefers sources from');
    expect(host.textContent).toContain('the last 30 days');
  });

  it('reads as a sentence for one day', () => {
    act(() => root.render(<JobParamsCard job={{ ...JOB, published_after_days: 1 }} />));
    expect(host.textContent).toContain('the last day');
  });

  it.each([[null], [undefined]])('shows no row when the run set none (%s)', (published_after_days) => {
    act(() => root.render(<JobParamsCard job={{ ...JOB, published_after_days }} />));
    expect(host.textContent).not.toContain('Prefers sources from');
  });
});
