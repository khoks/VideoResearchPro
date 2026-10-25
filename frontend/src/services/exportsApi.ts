// Downloads from the dataset and notes export endpoints.
//
// The files stream from the API behind the bearer header. Until T-8.8.1.5
// they were plain links carrying the JWT as `?token=`, which leaked it into
// history, logs and Referer headers; they are now fetched with the header and
// saved from a blob: URL (services/apiFiles.ts).
import { downloadApiFile } from './apiFiles';

export const EXPORT_FILES = {
  qaOpenai: { path: '/exports/qa-dataset/openai.jsonl', filename: 'qa-dataset-openai.jsonl' },
  qaTuple: { path: '/exports/qa-dataset/tuple.jsonl', filename: 'qa-dataset-tuple.jsonl' },
  knowledgeOpenai: { path: '/exports/knowledge-dataset/openai.jsonl', filename: 'knowledge-dataset-openai.jsonl' },
  knowledgeTuple: { path: '/exports/knowledge-dataset/tuple.jsonl', filename: 'knowledge-dataset-tuple.jsonl' },
  /** The user's notes as W3C Web Annotation JSON-LD, one per line (lossless). */
  notesJsonld: { path: '/exports/notes.jsonl', filename: 'notes.jsonl' },
  /** The user's notes as a Markdown document grouped by target. */
  notesMarkdown: { path: '/exports/notes.md', filename: 'notes.md' },
} as const;

export type ExportFile = keyof typeof EXPORT_FILES;

export const exportsApi = {
  /** Fetch one export with the header and save it under its file name. */
  download: (file: ExportFile): Promise<void> =>
    downloadApiFile(EXPORT_FILES[file].path, EXPORT_FILES[file].filename),
};
