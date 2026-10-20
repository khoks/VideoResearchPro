/**
 * S-1.18.2 (T-1.18.2.3): a report citation whose video has a frame near the
 * cited moment gets that still on its card; one without gets none.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useCitationStills } from '../useVideoFrames';
import type { CitationIndex, ResolvedCitation } from '../../components/reader/citations';
import type { CitationStill } from '../../components/reader/CitationCard';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const listMock = vi.fn();
const blobMock = vi.fn(async (_v: string, _f: string) => new Blob(['jpeg']));
vi.mock('../../services/framesApi', () => ({
  framesApi: { list: (id: string) => listMock(id), imageBlob: (v: string, f: string) => blobMock(v, f) },
}));

const citation = (index: number, videoId: string | null, seconds: number | null): ResolvedCitation =>
  ({
    index, href: null, videoId, seconds, label: '', contexts: [],
    source: videoId ? { video_id: videoId, document_id: `doc-${videoId}` } : null,
    resolvedHref: null, resolvedBy: 'video_id', footnote: index,
  }) as unknown as ResolvedCitation;

function indexOf(cs: ResolvedCitation[]): CitationIndex {
  return { byIndex: new Map(cs.map((c) => [c.index, c])), endnotes: [], unresolved: 0 };
}

let host: HTMLDivElement;
let root: Root;
let resolve: ((c: ResolvedCitation) => CitationStill | null) | null = null;

function Harness({ index }: { index: CitationIndex }) {
  resolve = useCitationStills(index);
  return null;
}

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  listMock.mockReset();
  blobMock.mockClear();
  URL.createObjectURL = vi.fn(() => 'blob:still');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('useCitationStills', () => {
  it('gives the nearest frame inside the window and nothing outside it', async () => {
    listMock.mockImplementation(async (id: string) => ({
      document_id: `doc-${id}`, video_id: id, visual_enabled: true, in_progress: false,
      frames: id === 'vidA'
        ? [{ frame_id: 'fA', timestamp_seconds: 250, timestamp_display: '4:10', description: 'a regression plot',
             informative: true, status: 'described', width: 640, height: 360, has_image: true }]
        : [],
    }));
    const cs = [citation(1, 'vidA', 200), citation(2, 'vidA', 500), citation(3, 'vidB', 10), citation(4, null, null)];
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() => root.render(<QueryClientProvider client={qc}><Harness index={indexOf(cs)} /></QueryClientProvider>));
    await flush();

    expect(listMock.mock.calls.map((c) => c[0]).sort()).toEqual(['vidA', 'vidB']);   // one request per video
    // Lazy: nothing is fetched until a card asks (a report cites ~200
    // moments; fetching them all at load spent the rate limit).
    expect(blobMock).not.toHaveBeenCalled();
    expect(resolve!(cs[1])).toBeNull();   // 300 s after the link: outside the window
    expect(resolve!(cs[2])).toBeNull();   // video without frames
    expect(resolve!(cs[3])).toBeNull();   // unresolved citation
    await flush();
    expect(blobMock).not.toHaveBeenCalled();

    expect(resolve!(cs[0])).toBeNull();   // first ask schedules the still
    await flush();
    expect(blobMock).toHaveBeenCalledTimes(1);
    expect(resolve!(cs[0])).toEqual({ src: 'blob:still', alt: 'On screen at 4:10: a regression plot' });
    expect(blobMock).toHaveBeenCalledTimes(1);   // fetched once, then reused
  });
});
