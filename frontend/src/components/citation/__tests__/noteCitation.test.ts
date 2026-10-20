import { describe, expect, it } from 'vitest';
import { renderCitation } from '../CitationLink';
import type { Reference } from '../../../types/qa';

const base: Reference = {
  source_type: 'note',
  video_url: '',
  video_title: 'Your note of 2026-10-19 on DNS explained',
  channel_name: 'you',
  timestamp_seconds: 0,
  timestamp_display: '',
  youtube_link: '',
  note_id: 'n1',
  note_created_at: '2026-10-19T11:24:45+00:00',
  quote: 'DNS resolves names…',
};

describe('note citations (S-8.5.2)', () => {
  it('reads like the note cards and names what the note is on', () => {
    const { label } = renderCitation({
      ...base,
      note_target_type: 'document',
      note_target_id: 'doc-dns',
      note_target_label: 'DNS explained',
    });
    expect(label.startsWith('You wrote this on ')).toBe(true);
    expect(label).toContain('2026');
    expect(label.endsWith(' · on DNS explained')).toBe(true);
  });

  it('links inside the app to the note target', () => {
    expect(renderCitation({ ...base, note_target_type: 'job', note_target_id: 'job-1' }).href).toBe('/jobs/job-1');
    expect(
      renderCitation({ ...base, note_target_type: 'qa_exchange', note_target_id: 'qa-1', note_target_parent_id: 'job-9' }).href,
    ).toBe('/jobs/job-9');
    expect(renderCitation({ ...base, note_target_type: 'channel', note_target_id: 'UCx' }).href).toBe('/library/channels/UCx');
  });

  it('falls back to the notes page when the target cannot be linked', () => {
    expect(renderCitation({ ...base, note_target_type: 'qa_exchange', note_target_id: 'qa-1' }).href).toBe('/notes');
    expect(renderCitation({ ...base, note_created_at: undefined }).label).toBe('Your note');
  });
});
