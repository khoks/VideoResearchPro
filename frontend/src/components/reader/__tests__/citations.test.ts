import { describe, expect, it } from 'vitest';
import { resolveCitations, timestampHref, type CitationSource } from '../citations';
import { parseCitationHref, parseReportHtml, type ReportCitation } from '../parseReport';
import { sanitizeReportHtml } from '../sanitize';
import { describeSource } from '../sourceLabels';
import { placeCard } from '../placeCard';
import sourcesFixture from '../__fixtures__/report-sources.json';
import bareAnchors from '../__fixtures__/report-topic-bare-anchors.html?raw';
import fullUrls from '../__fixtures__/report-topic-full-urls.html?raw';

const fixtures = sourcesFixture as Record<string, CitationSource[]>;

function src(over: Partial<CitationSource>): CitationSource {
  return {
    document_id: 'doc-1',
    video_id: 'abcdefghijk',
    source_type: 'video',
    title: 'How DNS resolution works',
    channel_name: 'Fireship',
    url: 'https://www.youtube.com/watch?v=abcdefghijk',
    source_url: null,
    duration_seconds: 300,
    published_at: '2024-03-01T00:00:00',
    thumbnail_url: null,
    source_metadata: {},
    ...over,
  };
}

function cite(href: string, label: string, index: number, contexts: string[] = []): ReportCitation {
  const c = parseCitationHref(href, label, index, contexts);
  if (!c) throw new Error(`not a citation: ${href}`);
  return c;
}

describe('resolveCitations', () => {
  it('resolves by the YouTube id in the href', () => {
    const idx = resolveCitations([cite('https://www.youtube.com/watch?v=abcdefghijk&t=42', '0:42', 1)], [src({})]);
    const r = idx.byIndex.get(1)!;
    expect(r.resolvedBy).toBe('video_id');
    expect(r.source?.title).toBe('How DNS resolution works');
    expect(r.resolvedHref).toBe('https://www.youtube.com/watch?v=abcdefghijk&t=42');
  });

  it('resolves a non-YouTube href against the document URL, ignoring the timestamp', () => {
    const pod = src({
      document_id: 'pod',
      video_id: null,
      source_type: 'podcast_episode',
      title: 'Episode 12',
      url: 'https://pod.example/ep/12',
    });
    const idx = resolveCitations([cite('https://pod.example/ep/12?t=90', '1:30', 1)], [src({}), pod]);
    expect(idx.byIndex.get(1)!.source?.document_id).toBe('pod');
    expect(idx.byIndex.get(1)!.resolvedBy).toBe('url');
  });

  it('recovers a bare &t= anchor from the title written beside it and rebuilds the link', () => {
    const c = cite('&t=75', '1:15', 1, ['Source: Fireship — How DNS resolution works, 1:15']);
    const r = resolveCitations([c], [src({}), src({ document_id: 'd2', video_id: 'zzzzzzzzzzz', title: 'Something else entirely' })]).byIndex.get(1)!;
    expect(r.resolvedBy).toBe('title');
    expect(r.resolvedHref).toBe('https://www.youtube.com/watch?v=abcdefghijk&t=75');
  });

  it('matches a title stem when the writer dropped the hashtags', () => {
    const s = src({ title: 'Health Care: BP tablets explained #bloodpressure #BP' });
    const c = cite('&t=5', '0:05', 1, ['Source: Someone — Health Care: BP tablets explained, 0:05']);
    expect(resolveCitations([c], [s]).byIndex.get(1)!.resolvedBy).toBe('title');
  });

  it('prefers the longer title when one title is a prefix of another', () => {
    const p1 = src({ document_id: 'p1', video_id: 'aaaaaaaaaaa', title: 'Seaborn tutorial' });
    const p2 = src({ document_id: 'p2', video_id: 'bbbbbbbbbbb', title: 'Seaborn tutorial part 2' });
    const c = cite('&t=1', '0:01', 1, ['From Seaborn tutorial part 2, 0:01']);
    expect(resolveCitations([c], [p1, p2]).byIndex.get(1)!.source?.document_id).toBe('p2');
  });

  it('falls back to a channel only when that channel has exactly one document in the run', () => {
    const solo = src({ document_id: 'solo', channel_name: 'Solo Channel', title: 'Unmentioned title one' });
    const a = src({ document_id: 'a', video_id: 'aaaaaaaaaaa', channel_name: 'Busy', title: 'Unmentioned title two' });
    const b = src({ document_id: 'b', video_id: 'bbbbbbbbbbb', channel_name: 'Busy', title: 'Unmentioned title three' });
    const idx = resolveCitations(
      [cite('&t=3', '0:03', 1, ['Solo Channel said so, 0:03']), cite('&t=4', '0:04', 2, ['Busy said so, 0:04'])],
      [solo, a, b],
    );
    expect(idx.byIndex.get(1)!.resolvedBy).toBe('channel');
    expect(idx.byIndex.get(2)!.source).toBeNull();
    expect(idx.byIndex.get(2)!.resolvedHref).toBeNull();
    expect(idx.unresolved).toBe(1);
  });

  it('never resolves an absolute href to a different document by title', () => {
    const c = cite('https://www.youtube.com/watch?v=unknownid00&t=9', '0:09', 1, ['How DNS resolution works']);
    const r = resolveCitations([c], [src({})]).byIndex.get(1)!;
    expect(r.source).toBeNull();
    expect(r.resolvedHref).toBe('https://www.youtube.com/watch?v=unknownid00&t=9');
  });

  it('shares one footnote between citations of the same place and counts them', () => {
    const idx = resolveCitations(
      [
        cite('https://www.youtube.com/watch?v=abcdefghijk&t=42', '0:42', 1),
        cite('https://www.youtube.com/watch?v=abcdefghijk&t=99', '1:39', 2),
        cite('https://www.youtube.com/watch?v=abcdefghijk&t=42', '0:42', 3),
      ],
      [src({})],
    );
    expect([1, 2, 3].map((i) => idx.byIndex.get(i)!.footnote)).toEqual([1, 2, 1]);
    expect(idx.endnotes.map((n) => [n.footnote, n.count])).toEqual([
      [1, 2],
      [2, 1],
    ]);
  });

  it('works before the document list arrives', () => {
    const idx = resolveCitations([cite('&t=1', '0:01', 1, ['x'])], []);
    expect(idx.byIndex.get(1)!.source).toBeNull();
    expect(idx.endnotes).toHaveLength(1);
  });
});

describe('resolveCitations on stored real reports', () => {
  it('recovers every bare anchor in the pre-S-1.14.9 smoke-test report', () => {
    const { citations } = parseReportHtml(sanitizeReportHtml(bareAnchors));
    expect(citations.length).toBe(30);
    expect(citations.every((c) => c.href === null)).toBe(true);
    const idx = resolveCitations(citations, fixtures['report-topic-bare-anchors']);
    expect(idx.unresolved).toBe(0);
    const via = new Set([...idx.byIndex.values()].map((r) => r.resolvedBy));
    expect([...via].every((v) => v === 'title' || v === 'channel')).toBe(true);
    for (const r of idx.byIndex.values()) {
      expect(r.resolvedHref).toMatch(/^https:\/\/www\.youtube\.com\/watch\?v=[\w-]{11}(&t=\d+)?$/);
    }
  });

  it('resolves every linked citation in the full-URL report by video id', () => {
    const { citations } = parseReportHtml(sanitizeReportHtml(fullUrls));
    const idx = resolveCitations(citations, fixtures['report-topic-full-urls']);
    expect(citations.length).toBeGreaterThan(200);
    const linked = [...idx.byIndex.values()].filter((r) => r.href);
    expect(linked.length).toBe(citations.length);
    expect(linked.every((r) => r.resolvedBy === 'video_id')).toBe(true);
    // Far fewer distinct places than chips: the endnote list dedupes.
    expect(idx.endnotes.length).toBeLessThan(citations.length);
  });
});

describe('timestampHref', () => {
  it('builds per-kind links', () => {
    expect(timestampHref(src({}), 30)).toBe('https://www.youtube.com/watch?v=abcdefghijk&t=30');
    expect(timestampHref(src({}), 0)).toBe('https://www.youtube.com/watch?v=abcdefghijk');
    expect(timestampHref(src({ video_id: null, source_type: 'podcast_episode', url: 'https://p.example/e' }), 12)).toBe(
      'https://p.example/e#t=12',
    );
    expect(timestampHref(src({ video_id: null, source_type: 'article', url: 'https://a.example/x' }), 12)).toBe(
      'https://a.example/x',
    );
    expect(timestampHref(src({ video_id: null, source_type: 'pdf', url: '', source_url: null }), 1)).toBeNull();
  });
});

describe('describeSource', () => {
  it('describes a video with channel, date and length', () => {
    expect(describeSource(src({}))).toEqual({ kind: 'YouTube video', meta: ['Fireship', '1 Mar 2024', '5:00'], timed: true });
  });

  it('treats a missing source_type as a video (responses before the schema fix)', () => {
    expect(describeSource(src({ source_type: undefined })).kind).toBe('YouTube video');
  });

  it('is polymorphic by source_type', () => {
    const reddit = describeSource(
      src({ source_type: 'reddit_post', published_at: null, source_metadata: { subreddit: 'python', author: 'ann' } }),
    );
    expect(reddit).toEqual({ kind: 'Reddit thread', meta: ['r/python', 'u/ann'], timed: false });
    const pdf = describeSource(src({ source_type: 'pdf', published_at: null, source_metadata: { page_count: 12 } }));
    expect(pdf).toEqual({ kind: 'PDF', meta: ['12 pages'], timed: false });
    const article = describeSource(
      src({ source_type: 'article', url: 'https://www.example.org/post', published_at: null, source_metadata: { author: 'B' } }),
    );
    expect(article).toEqual({ kind: 'Article', meta: ['example.org', 'B'], timed: false });
    expect(describeSource(src({ source_type: 'something_new' })).kind).toBe('Source');
  });
});

describe('placeCard', () => {
  const viewport = { width: 1000, height: 800 };
  const card = { width: 300, height: 150 };

  it('goes below and centred when it fits', () => {
    expect(placeCard({ top: 100, left: 400, width: 40, height: 20 }, card, viewport)).toEqual({
      top: 128,
      left: 270,
      side: 'below',
    });
  });

  it('flips above near the bottom of the viewport', () => {
    const p = placeCard({ top: 700, left: 400, width: 40, height: 20 }, card, viewport);
    expect(p.side).toBe('above');
    expect(p.top).toBe(700 - 8 - 150);
  });

  it('clamps inside the viewport horizontally', () => {
    expect(placeCard({ top: 100, left: 2, width: 20, height: 20 }, card, viewport).left).toBe(8);
    expect(placeCard({ top: 100, left: 990, width: 20, height: 20 }, card, viewport).left).toBe(1000 - 300 - 8);
  });

  it('stays on screen when neither side fits', () => {
    const p = placeCard({ top: 60, left: 10, width: 20, height: 20 }, { width: 300, height: 790 }, viewport);
    expect(p.side).toBe('below');
    expect(p.top).toBeGreaterThanOrEqual(8);
  });
});
