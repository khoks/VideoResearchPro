/**
 * Polymorphic ApprovalCard module — public exports.
 *
 * Per D-016 / D-018: a single polymorphic component family driven by
 * source_type + source_metadata. Adding a new source type is a config
 * entry, not a new component file. The mapped-type registry in
 * `types.ts` enforces this at compile time.
 *
 * Components:
 *   - <ClassificationBadgeRow> — D-007/D-014/D-021 four-axis badges
 *   - <ApprovalCard> — coming with T-1.5.4.1 follow-on PR
 *   - <CardHeader>, <CardBody>, <CardMetaRow>, <CardActions> — same
 */
export {
  ClassificationBadgeRow,
  type ClassificationBadgeRowProps,
} from './ClassificationBadgeRow';
export type {
  ApprovalCardConfig,
  ApprovalCardProps,
  ApprovalDocument,
  Classification,
  FilterChip,
  FormatterName,
  MetaChip,
  MetadataFor,
  SourceConfigRegistry,
  SourceMetadata,
  SourceType,
} from './types';
