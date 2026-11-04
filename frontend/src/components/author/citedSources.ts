// Grouping for the reader's Sources list (S-6.7.3, OutputSources.tsx): the
// citations `GET /author/outputs/{id}/citations` returns, one entry per cited
// source in first-cited order, the unmatched ones last.
import type { OutputCitation } from '../../services/authorApi';

export interface CitedSource {
  /** `document_id`, or null for the citations nothing matched. */
  documentId: string | null;
  title: string;
  channel: string | null;
  citations: OutputCitation[];
}

/** Only web links and this app's own API files are followed; anything else is shown as text. */
export function followableHref(url: string | null | undefined): string | null {
  if (!url) return null;
  if (/^https?:\/\//i.test(url) || url.startsWith('/api/v1/')) return url;
  return null;
}

/** Group citations by source, sources in first-cited order, unmatched last. */
export function groupCitations(citations: OutputCitation[]): CitedSource[] {
  const ordered = [...citations].sort((a, b) => a.position - b.position);
  const bySource = new Map<string, CitedSource>();
  const unmatched: OutputCitation[] = [];
  for (const c of ordered) {
    if (!c.document_id) {
      unmatched.push(c);
      continue;
    }
    let group = bySource.get(c.document_id);
    if (!group) {
      group = {
        documentId: c.document_id,
        title: c.title?.trim() || 'Untitled source',
        channel: c.channel_name?.trim() || null,
        citations: [],
      };
      bySource.set(c.document_id, group);
    }
    group.citations.push(c);
  }
  const groups = [...bySource.values()];
  if (unmatched.length) {
    groups.push({
      documentId: null,
      title: 'Not matched to a source in your library',
      channel: null,
      citations: unmatched,
    });
  }
  return groups;
}
