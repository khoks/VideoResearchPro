/** S-1.5.14: a run says what happened to its sources. */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { RunNotes } from '../RunNotes';
import type { Job, RunNote } from '../../../types/job';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

const REFUSED: RunNote = {
  kind: 'source_unavailable',
  source_type: 'bluesky_post',
  text: 'Bluesky was unavailable: it refused the search (HTTP 403).',
};
const MOVED: RunNote = {
  kind: 'budget_moved',
  text: '3 results that Bluesky could not fill went to YouTube (3).',
};

function mount(status: Job['status'], run_notes?: RunNote[]) {
  act(() => root.render(<RunNotes job={{ status, run_notes }} />));
  return host.querySelector('[data-testid="run-notes"]');
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('RunNotes', () => {
  it('renders nothing for a run with nothing to say', () => {
    expect(mount('awaiting_approval', [])).toBeNull();
    expect(mount('awaiting_approval', undefined)).toBeNull();
  });

  it('shows what the server wrote', () => {
    const notes = mount('awaiting_approval', [REFUSED, MOVED]);
    expect(notes?.getAttribute('role')).toBe('note');
    expect(Array.from(notes?.querySelectorAll('li') ?? []).map((li) => li.textContent)).toEqual([
      REFUSED.text,
      MOVED.text,
    ]);
  });

  it('leaves a failed run to its error, which names what was unavailable', () => {
    expect(mount('failed', [REFUSED])).toBeNull();
    expect(mount('failed', [REFUSED, MOVED])?.textContent).toContain(MOVED.text);
  });
});
