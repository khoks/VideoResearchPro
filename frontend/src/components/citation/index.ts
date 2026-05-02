/**
 * Polymorphic citation rendering — S-1.5.5.
 *
 * Public exports:
 *   - <CitationLink reference={ref} />  — renders one Reference
 *   - renderCitation(ref) → {href, label}  — pure dispatcher (testable)
 */
export { CitationLink, renderCitation, type CitationLinkProps } from './CitationLink';
