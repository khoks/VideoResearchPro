/**
 * Reading room (E-8.8).
 *
 * Pipeline: `sanitizeReportHtml` → `parseReportHtml` → `<ReaderShell>`.
 * The parser must only ever see the sanitiser's output.
 */
export { sanitizeReportHtml } from './sanitize';
export {
  parseReportHtml,
  parseCitationHref,
  type OutlineEntry,
  type ParsedReport,
  type ParseReportOptions,
  type ReportCitation,
} from './parseReport';
export { ReaderShell, type ReaderShellProps } from './ReaderShell';
export { parseMarkdownDoc, type ParsedMarkdown, type ParseMarkdownOptions } from './parseMarkdown';
export { StatTiles, type StatTile } from './StatTiles';
export { ProcessingNote } from './ProcessingNote';
export { ReaderCitation } from './ReaderCitation';
export { CitationCard, type CitationStill } from './CitationCard';
export { CitationCardProvider, useCitationUi, CITATION_CARD_ID } from './CitationContext';
export { Endnotes } from './Endnotes';
export {
  resolveCitations,
  timestampHref,
  type CitationIndex,
  type CitationSource,
  type Endnote,
  type ResolvedCitation,
} from './citations';
export { describeSource, formatPublished, type SourceDescription } from './sourceLabels';
export { placeCard, type Placement } from './placeCard';
export { Outline } from './Outline';
export { ReadingProgress, useReadingProgress } from './ReadingProgress';
export { useActiveHeading } from './useActiveHeading';
export { slugify, makeSlugger } from './slug';
