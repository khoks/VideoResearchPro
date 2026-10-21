/** S-1.18.2 (T-1.18.2.4): frames on the per-video page, and capture on demand. */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VideoFramesPanel } from '../VideoFramesPanel';
import type { FramesResponse } from '../../../utils/frames';
import { featureFlags } from '../../../config/features';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const listMock = vi.fn<(id: string) => Promise<FramesResponse>>();
const blobMock = vi.fn(async () => new Blob(['jpeg']));
const extractMock = vi.fn(async (_id: string, _force: boolean) => ({ status: 'queued', document_id: 'd1' }));
vi.mock('../../../services/framesApi', () => ({
  framesApi: {
    list: (id: string) => listMock(id),
    imageBlob: () => blobMock(),
    extract: (_id: string, force: boolean) => extractMock(_id, force),
  },
}));
let modelsOk = true;
vi.mock('../../../hooks/useFeatureAvailable', () => ({ useFeatureAvailable: () => modelsOk }));

const frame = (ts: number) => ({
  frame_id: `f${ts}`, timestamp_seconds: ts, timestamp_display: `0:${ts}`, description: `chart ${ts}`,
  informative: true, status: 'described', width: 640, height: 360, has_image: true,
});

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 5; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

async function mount() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  act(() => root.render(<QueryClientProvider client={qc}><VideoFramesPanel videoId="vid1" /></QueryClientProvider>));
  await flush();
}

const captureButton = () =>
  Array.from(host.querySelectorAll('button')).find((b) => /capture/i.test(b.textContent ?? '')) as HTMLButtonElement | undefined;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  modelsOk = true;
  featureFlags.visualAnalysis = true;   // capture shown; the hidden state has its own block
  listMock.mockReset();
  extractMock.mockClear();
  URL.createObjectURL = vi.fn(() => 'blob:frame');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('VideoFramesPanel', () => {
  it('shows each still with its time linked into the video', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: false, frames: [frame(12), frame(45)] });
    await mount();
    expect(host.querySelectorAll('img')).toHaveLength(2);
    const link = host.querySelector('a') as HTMLAnchorElement;
    expect(link.href).toContain('watch?v=vid1&t=12s');
    expect(host.textContent).toContain('chart 45');
    expect(captureButton()?.textContent).toBe('Recapture frames');
  });

  it('captures on demand when there are no frames yet', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: false, frames: [] });
    await mount();
    act(() => captureButton()!.click());
    await flush();
    expect(extractMock).toHaveBeenCalledWith('vid1', false);
  });

  it('disables capture when the install switch is off but still shows stored frames', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: false, in_progress: false, frames: [frame(12)] });
    await mount();
    expect(host.querySelectorAll('img')).toHaveLength(1);
    expect(captureButton()!.disabled).toBe(true);
    expect(captureButton()!.title).toContain('VISUAL_ENABLED');
  });

  it('says a capture is running and does not offer another', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: true, frames: [] });
    await mount();
    expect(host.textContent).toContain('Capturing frames');
    expect(captureButton()!.disabled).toBe(true);
  });

  it('renders nothing when there are no frames and nothing can be captured', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: false, in_progress: false, frames: [] });
    await mount();
    expect(host.querySelector('[data-testid="video-frames-panel"]')).toBeNull();
  });

  it('explains a spent monthly quota', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: false, frames: [] });
    extractMock.mockRejectedValueOnce({ response: { status: 429, data: { detail: 'quota' } } });
    await mount();
    act(() => captureButton()!.click());
    await flush();
    expect(host.textContent).toContain("this month's frame captures");
  });
});

describe('VideoFramesPanel with visual analysis hidden (D-105)', () => {
  beforeEach(() => {
    featureFlags.visualAnalysis = false;
  });

  it('still shows existing stills but offers no capture', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: false, frames: [frame(12)] });
    await mount();
    expect(host.querySelectorAll('img')).toHaveLength(1);
    expect(captureButton()).toBeUndefined();
  });

  it('renders nothing when there are no frames', async () => {
    listMock.mockResolvedValue({ document_id: 'd1', video_id: 'vid1', visual_enabled: true, in_progress: false, frames: [] });
    await mount();
    expect(host.querySelector('[data-testid="video-frames-panel"]')).toBeNull();
  });
});
