/**
 * T-8.8.1.5: the quick peek's frame URL is created once per blob, revoked
 * when the blob changes or the component unmounts, and never handed out
 * after it was revoked — StrictMode's double mount included.
 */
import { StrictMode, act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useObjectUrl } from '../useObjectUrl';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let seen: Array<string | null>;
let live: Set<string>;

let revokedAtRender: string[];

function Probe({ blob }: { blob: Blob | null }) {
  const url = useObjectUrl(blob);
  seen.push(url);
  if (url && !live.has(url)) revokedAtRender.push(url);
  return null;
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  seen = [];
  revokedAtRender = [];
  live = new Set();
  let n = 0;
  URL.createObjectURL = vi.fn(() => {
    const url = `blob:test/${++n}`;
    live.add(url);
    return url;
  });
  URL.revokeObjectURL = vi.fn((url: string) => {
    live.delete(url);
  });
});

afterEach(() => {
  host.remove();
});

describe('useObjectUrl', () => {
  it('is null without a blob and creates nothing', () => {
    act(() => root.render(<Probe blob={null} />));
    expect(seen.at(-1)).toBeNull();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    act(() => root.unmount());
  });

  it('creates a URL for the blob, swaps it when the blob changes, and revokes on unmount', () => {
    const a = new Blob(['a']);
    const b = new Blob(['b']);
    act(() => root.render(<Probe blob={a} />));
    const first = seen.at(-1)!;
    expect(first).toMatch(/^blob:/);
    expect(live.has(first)).toBe(true);

    act(() => root.render(<Probe blob={b} />));
    const second = seen.at(-1)!;
    expect(second).not.toBe(first);
    expect(live.has(first)).toBe(false); // the old one is revoked
    expect(live.has(second)).toBe(true);

    act(() => root.unmount());
    expect(live.size).toBe(0);
    expect(revokedAtRender).toEqual([]);
  });

  it('never returns a revoked URL under StrictMode', () => {
    const a = new Blob(['a']);
    act(() =>
      root.render(
        <StrictMode>
          <Probe blob={a} />
        </StrictMode>,
      ),
    );
    const url = seen.at(-1)!;
    expect(url).toMatch(/^blob:/);
    expect(live.has(url)).toBe(true);
    expect(revokedAtRender).toEqual([]);
    act(() => root.unmount());
    expect(live.size).toBe(0);
  });
});
