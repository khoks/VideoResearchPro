/**
 * The `context` "Confirm & search" sends after the clarify step, for job Q&A
 * (`POST /jobs/{id}/qa`) and library or shelf Q&A (`POST /library/qa`,
 * `POST /shelves/{id}/qa`). The backend folds it into the agent's question
 * (`qa_prompts.with_clarification`, S-8.13.1).
 */

/** The server's bound on `context` (`QARequest` and `LibraryQARequest`,
 *  `max_length=4000`). Over it the ask is a 422, so the page never sends more. */
export const CLARIFY_CONTEXT_MAX_CHARS = 4000;

/** Per-answer cap on the clarify inputs. Three answers at the cap, with
 *  their questions, still fit under {@link CLARIFY_CONTEXT_MAX_CHARS}. */
export const CLARIFY_ANSWER_MAX_CHARS = 1000;

const INTERPRETATION_PREFIX = 'My interpretation: ';
const SEPARATOR = '\n\n';

/** `text` cut to at most `max` UTF-16 units, never splitting a surrogate pair
 *  (a lone surrogate does not survive the JSON round trip to the server). */
function clip(text: string, max: number): string {
  if (text.length <= max) return text;
  const cut = text.slice(0, Math.max(0, max));
  const last = cut.charCodeAt(cut.length - 1);
  return last >= 0xd800 && last <= 0xdbff ? cut.slice(0, -1) : cut;
}

/**
 * The interpretation the reader confirmed, then each clarifying question they
 * answered with its answer (unanswered ones are left out), at most
 * `maxChars` long. The interpretation is unbounded model output, so it is
 * what gives way: the reader's own answers keep the room they need and the
 * interpretation is shortened, with an ellipsis, to what is left. Only when
 * the answers alone overflow is the whole text cut at the end.
 */
export function buildClarifyContext(
  interpretation: string,
  clarifications: string[],
  answers: string[],
  maxChars: number = CLARIFY_CONTEXT_MAX_CHARS,
): string {
  const answered = clarifications
    .map((q, i) => (answers[i]?.trim() ? `${q}\n${answers[i].trim()}` : null))
    .filter((part): part is string => part !== null);
  const tail = answered.map((part) => SEPARATOR + part).join('');

  const room = maxChars - INTERPRETATION_PREFIX.length - tail.length;
  const shown = interpretation.length <= room ? interpretation : `${clip(interpretation, room - 1)}…`;
  return clip(`${INTERPRETATION_PREFIX}${room > 0 ? shown : ''}${tail}`, maxChars);
}
