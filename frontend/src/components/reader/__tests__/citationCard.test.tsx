/**
 * The card wired through the provider, in jsdom: focus opens it with
 * aria-describedby on the chip, Escape and blur close it, unresolved chips
 * are keyboard-reachable buttons, and the R1 still slot renders when fed.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { CitationCardProvider, CITATION_CARD_ID } from '../CitationContext';
import { Endnotes } from '../Endnotes';
import { ReaderCitation } from '../ReaderCitation';
import { resolveCitations, type CitationSource } from '../citations';
import { parseReportHtml } from '../parseReport';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const SOURCE: CitationSource = {
  document_id: 'doc-1',
  video_id: 'abcdefghijk',
  source_type: 'video',
  title: 'How DNS resolution works',
  channel_name: 'Fireship',
  url: 'https://www.youtube.com/watch?v=abcdefghijk',
  source_url: null,
  duration_seconds: 300,
  published_at: null,
  thumbnail_url: null,
  source_metadata: {},
};

const HTML =
  '<p>Linked <a href="https://www.youtube.com/watch?v=abcdefghijk&t=42">0:42</a> and ' +
  'bare <a href="&t=7">0:07</a> and lost <a href="&t=9">0:09</a>.</p>';

let host: HTMLDivElement;
let root: Root;

function mount(withStill = false) {
  const parsed = parseReportHtml(HTML, {
    renderCitation: (c) => <ReaderCitation key={c.index} citation={c} />,
  });
  // Citation 2 is recoverable from its context only if the title is there;
  // here it is not, so give its context the title by hand.
  parsed.citations[1].contexts = ['Fireship — How DNS resolution works, 0:07'];
  const index = resolveCitations(parsed.citations, [SOURCE]);
  act(() => {
    root.render(
      <CitationCardProvider
        index={index}
        resolveStill={withStill ? () => ({ src: '/frames/x.jpg', alt: 'A still at 0:42' }) : undefined}
      >
        <div>{parsed.content}</div>
        <Endnotes endnotes={index.endnotes} />
      </CitationCardProvider>,
    );
  });
  return index;
}

function card(): HTMLElement {
  return document.getElementById(CITATION_CARD_ID)!;
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

describe('citation card', () => {
  it('opens on focus with the source, and the chip points at it', () => {
    mount();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    expect(card().style.display).toBe('none');
    act(() => chip.focus());
    expect(card().style.display).toBe('block');
    expect(card().textContent).toContain('How DNS resolution works');
    expect(card().textContent).toContain('Fireship');
    expect(card().textContent).toContain('YouTube video');
    expect(card().textContent).toContain('Open at 0:42');
    expect(chip.getAttribute('aria-describedby')).toBe(CITATION_CARD_ID);
    expect(card().getAttribute('role')).toBe('tooltip');
  });

  it('closes on Escape and on blur', () => {
    mount();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    act(() => chip.focus());
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    });
    expect(card().style.display).toBe('none');
    expect(chip.hasAttribute('aria-describedby')).toBe(false);
    expect(document.activeElement).toBe(chip); // Escape closes the card, not the focus
    act(() => chip.blur());
    act(() => chip.focus());
    expect(card().style.display).toBe('block');
    act(() => chip.blur());
    expect(card().style.display).toBe('none');
  });

  it('stays open when the page scrolls under it, and follows its chip', async () => {
    mount();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    act(() => chip.focus());
    await act(async () => {
      window.dispatchEvent(new Event('scroll'));
      await new Promise((r) => requestAnimationFrame(() => r(null)));
    });
    expect(card().style.display).toBe('block');
    expect(chip.getAttribute('aria-describedby')).toBe(CITATION_CARD_ID);
  });

  it('links a recovered bare anchor and explains how it was matched', () => {
    mount();
    const chips = host.querySelectorAll<HTMLElement>('.reader-citation');
    expect(chips).toHaveLength(3);
    const recovered = chips[1] as HTMLAnchorElement;
    expect(recovered.tagName).toBe('A');
    expect(recovered.getAttribute('href')).toBe('https://www.youtube.com/watch?v=abcdefghijk&t=7');
    act(() => recovered.focus());
    expect(card().textContent).toContain('Matched by the title');
  });

  it('keeps an unrecoverable citation reachable as a button with an explanatory card', () => {
    mount();
    const lost = host.querySelectorAll<HTMLElement>('.reader-citation')[2];
    expect(lost.tagName).toBe('BUTTON');
    expect(lost.getAttribute('aria-label')).toContain('source not recorded');
    act(() => lost.focus());
    expect(card().textContent).toContain('did not record which source');
    expect(card().querySelector('a')).toBeNull();
  });

  it('numbers chips for print and lists them as endnotes', () => {
    const index = mount();
    const fns = [...host.querySelectorAll('.reader-fn')].map((n) => n.textContent);
    expect(fns).toEqual(['1', '2', '3']);
    expect(index.endnotes).toHaveLength(3);
    const items = host.querySelectorAll('.reader-endnotes li');
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain('How DNS resolution works');
    expect(items[2].textContent).toContain('source not recorded');
  });

  it('opens the endnotes for printing and restores them afterwards', () => {
    mount();
    const details = host.querySelector('.reader-endnotes details') as HTMLDetailsElement;
    expect(details.open).toBe(false);
    act(() => {
      window.dispatchEvent(new Event('beforeprint'));
    });
    expect(details.open).toBe(true);
    act(() => {
      window.dispatchEvent(new Event('afterprint'));
    });
    expect(details.open).toBe(false);
  });

  it('shows an R1 still when one is supplied (T-8.8.2.3 hook)', () => {
    mount(true);
    act(() => host.querySelector<HTMLAnchorElement>('a.reader-citation')!.focus());
    const img = card().querySelector('img')!;
    expect(img.getAttribute('src')).toBe('/frames/x.jpg');
    expect(img.getAttribute('alt')).toBe('A still at 0:42');
  });
});
