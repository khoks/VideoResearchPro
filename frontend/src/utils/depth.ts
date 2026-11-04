/*
 * R4 / D-064: the depth a reader asks for on one answer or one knowledge
 * report. `null` is "no preference": the request carries no `output_length`
 * and the server falls back exactly as before (the job's setting, else the
 * corpus bracket for Q&A; the size-based budget for a knowledge report).
 */
import type { OutputLength } from '../types/job';

export type Depth = Exclude<OutputLength, 'auto'>;

export const DEPTHS: readonly Depth[] = ['brief', 'standard', 'deep'];

const LABELS: Record<Depth, string> = { brief: 'Brief', standard: 'Standard', deep: 'Deep' };

export function depthLabel(depth: Depth): string {
  return LABELS[depth];
}

/** A stored or typed value as a depth; 'auto', unknown and empty are none. */
export function depthOf(value: string | null | undefined): Depth | null {
  return value && (DEPTHS as readonly string[]).includes(value) ? (value as Depth) : null;
}

/** The request body with `output_length` only when a depth was chosen. */
export function withDepth<T extends object>(body: T, depth: Depth | null): T & { output_length?: Depth } {
  return depth ? { ...body, output_length: depth } : body;
}
