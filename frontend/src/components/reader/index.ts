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
export { ReaderCitation } from './ReaderCitation';
export { Outline } from './Outline';
export { ReadingProgress, useReadingProgress } from './ReadingProgress';
export { useActiveHeading } from './useActiveHeading';
export { slugify, makeSlugger } from './slug';
