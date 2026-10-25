import { describe, expect, it } from 'vitest';
import {
  buildClarifyContext,
  CLARIFY_ANSWER_MAX_CHARS,
  CLARIFY_CONTEXT_MAX_CHARS,
} from '../clarifyContext';

// The server refuses a `context` over 4,000 characters with a 422
// (backend/app/schemas/library_qa.py and schemas/qa.py), so "Confirm &
// search" must never build one longer, whatever the model or the reader wrote.

describe('buildClarifyContext', () => {
  it('is the interpretation then each answered question with its answer', () => {
    expect(
      buildClarifyContext('You want the rate moves since 2024.', ['Which central bank?', 'Over what period?'], ['The RBI', '  ']),
    ).toBe('My interpretation: You want the rate moves since 2024.\n\nWhich central bank?\nThe RBI');
  });

  it('is the interpretation alone when nothing was answered', () => {
    expect(buildClarifyContext('A primer.', ['Which records?'], [''])).toBe('My interpretation: A primer.');
  });

  it('shortens a long interpretation and keeps every answer whole', () => {
    const answers = ['a'.repeat(CLARIFY_ANSWER_MAX_CHARS), 'b'.repeat(CLARIFY_ANSWER_MAX_CHARS), 'c'.repeat(CLARIFY_ANSWER_MAX_CHARS)];
    const context = buildClarifyContext('x'.repeat(6000), ['Q1?', 'Q2?', 'Q3?'], answers);

    expect(context.length).toBe(CLARIFY_CONTEXT_MAX_CHARS);
    expect(context.startsWith('My interpretation: xxx')).toBe(true);
    expect(context).toContain('x…\n\nQ1?\n');
    expect(context.endsWith(`Q1?\n${answers[0]}\n\nQ2?\n${answers[1]}\n\nQ3?\n${answers[2]}`)).toBe(true);
  });

  it('three answers at the input cap, with their questions, fit beside an interpretation', () => {
    const answers = Array(3).fill('a'.repeat(CLARIFY_ANSWER_MAX_CHARS));
    const questions = Array(3).fill('q'.repeat(200));
    const context = buildClarifyContext('A primer.', questions, answers);
    expect(context.length).toBeLessThanOrEqual(CLARIFY_CONTEXT_MAX_CHARS);
    expect(context.startsWith('My interpretation: A primer.\n\n')).toBe(true);
  });

  it('cuts at the end only when the answers alone overflow', () => {
    const context = buildClarifyContext('A primer.', ['Q1?', 'Q2?'], ['a'.repeat(3000), 'b'.repeat(3000)]);
    expect(context.length).toBe(CLARIFY_CONTEXT_MAX_CHARS);
    expect(context.startsWith('My interpretation: \n\nQ1?\n')).toBe(true);
  });

  it('never ends on half of a surrogate pair', () => {
    // Emoji are two UTF-16 units each; at this bound the interpretation's
    // room is odd, so a plain slice would end on a lone high surrogate.
    const context = buildClarifyContext('🙂'.repeat(2500), [], [], 2001);
    expect(context.length).toBeLessThanOrEqual(2001);
    const last = context.charCodeAt(context.length - 2);
    expect(context.endsWith('…')).toBe(true);
    expect(last >= 0xd800 && last <= 0xdbff).toBe(false);
  });
});
