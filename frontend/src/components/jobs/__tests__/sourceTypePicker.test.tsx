/** S-1.5.13 (T-1.5.13.3): the topic run's source picker. */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceTypePicker } from '../SourceTypePicker';
import type { SourceType } from '../../../utils/jobForm';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

function mount(selected: SourceType[], capabilities: Record<string, boolean> | null, numVideos = 10) {
  const onChange = vi.fn();
  act(() =>
    root.render(
      <SourceTypePicker selected={selected} onChange={onChange} capabilities={capabilities} numVideos={numVideos} />,
    ),
  );
  const chips = Array.from(host.querySelectorAll<HTMLButtonElement>('button[data-source-type]'));
  const chip = (value: string) => chips.find((b) => b.dataset.sourceType === value);
  return { onChange, chips, chip };
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

describe('SourceTypePicker', () => {
  it('offers the ungated sources with YouTube on by default, and no note', () => {
    const { chips, chip } = mount(['video'], {});
    expect(chips.map((b) => b.dataset.sourceType)).toEqual([
      'video',
      'hn_story',
      'mastodon_post',
      'bluesky_post',
      'podcast_episode',
    ]);
    expect(chip('video')?.getAttribute('aria-pressed')).toBe('true');
    expect(chip('hn_story')?.getAttribute('aria-pressed')).toBe('false');
    expect(host.querySelector('[data-testid="source-type-note"]')).toBeNull();
  });

  it('hides X / Twitter until /health reports tweet search on', () => {
    expect(mount(['video'], null).chip('tweet')).toBeUndefined();
    expect(mount(['video'], { twitter_search_enabled: false }).chip('tweet')).toBeUndefined();
    expect(mount(['video'], { twitter_search_enabled: true }).chip('tweet')).toBeDefined();
  });

  it('adds a source in canonical order', () => {
    const { onChange, chip } = mount(['video'], { reddit_search_enabled: true });
    act(() => chip('hn_story')!.click());
    expect(onChange).toHaveBeenLastCalledWith(['video', 'hn_story']);
    act(() => chip('reddit_post')!.click());
    expect(onChange).toHaveBeenLastCalledWith(['video', 'reddit_post']);
  });

  it('shows a carried source the install lacks, struck through and removable', () => {
    const { onChange, chip } = mount(['video', 'tweet'], { twitter_search_enabled: false });
    const tweet = chip('tweet')!;
    expect(tweet.style.textDecoration).toBe('line-through');
    expect(host.textContent).toContain('X / Twitter is not set up on this install');
    act(() => tweet.click());
    expect(onChange).toHaveBeenLastCalledWith(['video']);
  });

  it('says what an empty or YouTube-less choice means', () => {
    mount([], {});
    expect(host.textContent).toContain('Choose at least one source');
    mount(['hn_story'], {});
    expect(host.textContent).toContain('do not apply');
  });

  it('says how the results split across several sources', () => {
    mount(['video', 'hn_story', 'podcast_episode'], {}, 10);
    const note = host.querySelector('[data-testid="source-type-note"]')!;
    expect(note.textContent).toContain('The 10 results you set below are shared across these sources: YouTube 4, Hacker News 3, Podcasts 3.');
    expect(note.getAttribute('role')).toBeNull();
  });

  it('flags fewer results than sources', () => {
    mount(['video', 'hn_story', 'podcast_episode'], {}, 2);
    const note = host.querySelector('[data-testid="source-type-note"]')!;
    expect(note.textContent).toContain('at least 3 results');
    expect(note.getAttribute('role')).toBe('alert');
  });
});
