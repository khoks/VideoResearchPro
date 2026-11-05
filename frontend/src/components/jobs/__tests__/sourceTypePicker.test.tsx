/** S-1.5.13 (T-1.5.13.3): the topic run's source picker. */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SourceTypePicker } from '../SourceTypePicker';
import type { SourceHold } from '../../../stores/systemStatusStore';
import type { SourceType } from '../../../utils/jobForm';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

function mount(
  selected: SourceType[],
  capabilities: Record<string, boolean> | null,
  numVideos = 10,
  holds?: Record<string, SourceHold>,
) {
  const onChange = vi.fn();
  act(() =>
    root.render(
      <SourceTypePicker
        selected={selected}
        onChange={onChange}
        capabilities={capabilities}
        numVideos={numVideos}
        holds={holds}
      />,
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

  it('stops offering a keyless source once /health says it cannot be searched', () => {
    expect(mount(['video'], null).chip('bluesky_post')).toBeDefined();
    expect(mount(['video'], { bluesky_search_enabled: true }).chip('bluesky_post')).toBeDefined();
    expect(mount(['video'], { bluesky_search_enabled: false }).chip('bluesky_post')).toBeUndefined();
  });

  it('says why a source that refused this install is gone, on the default form too', () => {
    const until = '2026-11-05T12:00:00+00:00';
    mount(['video'], { bluesky_search_enabled: false }, 10, { bluesky_post: { status: 403, until } });
    expect(host.querySelector('[data-testid="source-type-held-note"]')?.textContent).toBe(
      'Bluesky refused its last search from this install, so it is not offered for now.',
    );
  });

  it('has no such note when nothing is on hold', () => {
    mount(['video'], {});
    expect(host.querySelector('[data-testid="source-type-held-note"]')).toBeNull();
    expect(host.querySelector('[data-testid="source-type-try-held"]')).toBeNull();
  });

  describe('try it anyway (T-1.5.14.6)', () => {
    const until = '2026-11-05T12:00:00+00:00';
    const held = { bluesky_post: { status: 403, until } };
    const caps = { bluesky_search_enabled: false };
    const tryButton = (value: string) => host.querySelector<HTMLButtonElement>(`button[data-try-held="${value}"]`);

    it('offers the held source, and choosing it puts it in this run', () => {
      const { onChange, chip } = mount(['video'], caps, 10, held);
      expect(chip('bluesky_post')).toBeUndefined();
      expect(tryButton('bluesky_post')?.textContent).toBe('Try Bluesky anyway');

      act(() => tryButton('bluesky_post')!.click());

      expect(onChange).toHaveBeenCalledWith(['video', 'bluesky_post']);
    });

    it('shows a held source in this run as chosen, and says plainly that it refused', () => {
      const { chip } = mount(['video', 'bluesky_post'], caps, 10, held);
      expect(chip('bluesky_post')?.getAttribute('aria-pressed')).toBe('true');
      expect(chip('bluesky_post')?.style.textDecoration).not.toBe('line-through');
      expect(host.querySelector('[data-testid="source-type-held-note"]')?.textContent).toContain(
        'Bluesky refused its last search from this install. This run tries it anyway',
      );
      expect(tryButton('bluesky_post')).toBeNull();
    });

    it('does not ask for a held source to be removed before submitting', () => {
      mount(['video', 'bluesky_post'], caps, 10, held);
      expect(host.querySelector('[data-testid="source-type-note"]')?.textContent).not.toContain('not set up');
      expect(host.querySelector('[role="alert"]')).toBeNull();
    });

    it('still shares the budget with it, because the run will ask it', () => {
      mount(['video', 'bluesky_post'], caps, 10, held);
      expect(host.querySelector('[data-testid="source-type-note"]')?.textContent).toContain('YouTube 5, Bluesky 5');
    });

    it('takes it back out with the chip', () => {
      const { onChange, chip } = mount(['video', 'bluesky_post'], caps, 10, held);
      act(() => chip('bluesky_post')!.click());
      expect(onChange).toHaveBeenCalledWith(['video']);
    });

    it('offers only the held sources left out, one button each', () => {
      const both = { ...held, hn_story: { status: 401, until } };
      mount(['bluesky_post'], { ...caps, hn_search_enabled: false }, 10, both);
      expect(tryButton('hn_story')).not.toBeNull();
      expect(tryButton('bluesky_post')).toBeNull();
    });

    it('still flags a source that is simply not set up', () => {
      const { chip } = mount(['video', 'bluesky_post', 'tweet'], { ...caps, twitter_search_enabled: false }, 10, held);
      expect(chip('tweet')?.style.textDecoration).toBe('line-through');
      expect(chip('bluesky_post')?.style.textDecoration).not.toBe('line-through');
      expect(host.querySelector('[role="alert"]')?.textContent).toBe(
        'X / Twitter is not set up on this install. Remove it to submit.',
      );
    });
  });

  it('strikes through a carried source that a blank base URL took away', () => {
    const { chip } = mount(['video', 'mastodon_post'], { mastodon_search_enabled: false });
    expect(chip('mastodon_post')?.style.textDecoration).toBe('line-through');
    expect(host.querySelector('[data-testid="source-type-note"]')?.textContent).toContain('not set up');
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
