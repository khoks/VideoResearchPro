/**
 * The card wired through the provider, in jsdom: focus opens it with
 * aria-describedby on the chip, Escape and blur close it, unresolved chips
 * are keyboard-reachable buttons, and the R1 still slot renders when fed.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import http from '../../../services/api';
import { stubNewTabs, type FakeTab } from '../../../services/__tests__/newTab';
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

  function pointerDown(el: Element, pointerType: 'touch' | 'mouse') {
    const ev = new Event('pointerdown', { bubbles: true, cancelable: true });
    Object.defineProperty(ev, 'pointerType', { value: pointerType });
    el.dispatchEvent(ev);
  }

  function click(el: HTMLElement): boolean {
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    el.dispatchEvent(ev);
    return ev.defaultPrevented;
  }

  it('on touch, the first tap on a linked chip previews its card and the second follows the link', () => {
    mount();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    let prevented = false;
    act(() => {
      pointerDown(chip, 'touch');
      chip.focus(); // a tap focuses the link before the click lands
      prevented = click(chip);
    });
    expect(prevented).toBe(true);
    expect(card().style.display).toBe('block');
    act(() => {
      pointerDown(chip, 'touch');
      prevented = click(chip);
    });
    expect(prevented).toBe(false); // second tap: the browser follows the link
  });

  it('a mouse click on a linked chip is never intercepted', () => {
    mount();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    let prevented = true;
    act(() => {
      pointerDown(chip, 'mouse');
      prevented = click(chip);
    });
    expect(prevented).toBe(false);
  });

  it('a tap outside the card and its chip closes the card', () => {
    mount();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    act(() => chip.focus());
    expect(card().style.display).toBe('block');
    act(() => pointerDown(card(), 'touch'));
    expect(card().style.display).toBe('block'); // inside the card: stays
    act(() => pointerDown(document.body, 'touch'));
    expect(card().style.display).toBe('none');
  });

  it('clicking an unresolved chip opens its card, and clicking again closes it', () => {
    mount();
    const lost = host.querySelectorAll<HTMLButtonElement>('.reader-citation')[2];
    act(() => {
      pointerDown(lost, 'mouse');
      lost.focus(); // Chromium focuses a button on mousedown, which opens the card
      click(lost);
    });
    expect(card().style.display).toBe('block');
    act(() => {
      pointerDown(lost, 'mouse');
      click(lost);
    });
    expect(card().style.display).toBe('none');
  });

  it('shows an R1 still when one is supplied (T-8.8.2.3 hook)', () => {
    mount(true);
    act(() => host.querySelector<HTMLAnchorElement>('a.reader-citation')!.focus());
    const img = card().querySelector('img')!;
    expect(img.getAttribute('src')).toBe('/frames/x.jpg');
    expect(img.getAttribute('alt')).toBe('A still at 0:42');
  });
});

describe('a cited uploaded PDF (E-1.8, T-8.8.1.5)', () => {
  // The serve route takes the bearer header only, so followed as a link the
  // permalink 401s in the new tab. Chip, card link and endnote each fetch
  // the PDF with the header and open its blob: URL instead.
  const PDF: CitationSource = {
    document_id: 'doc-pdf',
    video_id: null,
    source_type: 'pdf',
    title: 'Annual report',
    channel_name: '',
    url: '/api/v1/library/pdf/abc.pdf',
    source_url: null,
    duration_seconds: null,
    published_at: null,
    thumbnail_url: null,
    source_metadata: {},
  };
  let get: ReturnType<typeof vi.spyOn>;
  let open: ReturnType<typeof vi.fn>;
  let tabs: FakeTab[];
  const saved = { create: URL.createObjectURL, revoke: URL.revokeObjectURL, open: window.open };

  beforeEach(() => {
    get = vi.spyOn(http, 'get').mockResolvedValue({ data: new Blob(['%PDF']) } as never);
    URL.createObjectURL = vi.fn(() => 'blob:http://localhost:5173/p1');
    URL.revokeObjectURL = vi.fn();
    ({ open, tabs } = stubNewTabs());
  });

  afterEach(() => {
    get.mockRestore();
    URL.createObjectURL = saved.create;
    URL.revokeObjectURL = saved.revoke;
    window.open = saved.open;
  });

  async function settle() {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }

  function mountPdf() {
    // A report cites with `&t=` anchors; a bare one is matched to its source
    // by title, and a PDF source resolves to its stored url, the serve route.
    const parsed = parseReportHtml('<p>Revenue rose <a href="&t=0">p. 3</a>.</p>', {
      renderCitation: (c) => <ReaderCitation key={c.index} citation={c} />,
    });
    parsed.citations[0].contexts = ['Annual report — revenue rose'];
    const index = resolveCitations(parsed.citations, [PDF]);
    act(() => {
      root.render(
        <CitationCardProvider index={index}>
          <div>{parsed.content}</div>
          <Endnotes endnotes={index.endnotes} />
        </CitationCardProvider>,
      );
    });
  }

  function clickAndOpen(el: Element): boolean {
    const ev = new MouseEvent('click', { bubbles: true, cancelable: true });
    act(() => {
      el.dispatchEvent(ev);
    });
    return ev.defaultPrevented;
  }

  it('the chip', async () => {
    mountPdf();
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    expect(chip.getAttribute('href')).toBe('/api/v1/library/pdf/abc.pdf');
    expect(clickAndOpen(chip)).toBe(true);
    expect(open).toHaveBeenCalledWith('', '_blank'); // inside the click, before the download
    await settle();
    expect(get).toHaveBeenCalledWith('/library/pdf/abc.pdf', { responseType: 'blob' });
    expect(tabs[0].location.href).toBe('blob:http://localhost:5173/p1');
  });

  it('the card link', async () => {
    mountPdf();
    act(() => host.querySelector<HTMLAnchorElement>('a.reader-citation')!.focus());
    const link = card().querySelector<HTMLAnchorElement>('a[href="/api/v1/library/pdf/abc.pdf"]')!;
    expect(clickAndOpen(link)).toBe(true);
    await settle();
    expect(open).toHaveBeenCalledWith('', '_blank');
    expect(tabs[0].location.href).toBe('blob:http://localhost:5173/p1');
  });

  it('the endnote', async () => {
    mountPdf();
    const note = host.querySelector<HTMLAnchorElement>('.reader-endnotes a[href="/api/v1/library/pdf/abc.pdf"]')!;
    expect(clickAndOpen(note)).toBe(true);
    await settle();
    expect(open).toHaveBeenCalledWith('', '_blank');
    expect(tabs[0].location.href).toBe('blob:http://localhost:5173/p1');
  });

  it('a chip the report wrote to any other API route stays a plain link', async () => {
    // The chip's own href wins over its source's, and the model writes it. A
    // generic fetch-and-open would GET the route with the header and show
    // the body top-level on the app's origin; only the PDF route opens.
    const href = `${window.location.origin}/api/v1/jobs/x/report?t=1`;
    const parsed = parseReportHtml(`<p>See <a href="${href}">this</a>.</p>`, {
      renderCitation: (c) => <ReaderCitation key={c.index} citation={c} />,
    });
    const index = resolveCitations(parsed.citations, [PDF]);
    act(() => {
      root.render(
        <CitationCardProvider index={index}>
          <div>{parsed.content}</div>
          <Endnotes endnotes={index.endnotes} />
        </CitationCardProvider>,
      );
    });
    const chip = host.querySelector<HTMLAnchorElement>('a.reader-citation')!;
    expect(chip.getAttribute('href')).toBe(href);
    const note = host.querySelector<HTMLAnchorElement>(`.reader-endnotes a[href="${href}"]`)!;
    expect(clickAndOpen(chip)).toBe(false);
    expect(clickAndOpen(note)).toBe(false);
    await settle();
    expect(get).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    expect(URL.createObjectURL).not.toHaveBeenCalled();
  });
});
