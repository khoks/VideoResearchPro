import { useJobStore } from '../../stores/jobStore';
import { TabBlockedError } from '../../services/apiFiles';

/** The toast when the browser refuses the tab a file was to open in. */
export const TAB_BLOCKED_MESSAGE =
  'Your browser blocked the new tab. Allow pop-ups for this site, then try again.';

/**
 * The toast for a cited file the API would not hand over (T-8.8.1.5): a PDF
 * citation opens through `openApiLink`, which fetches with the header, or
 * for the tab it was to open in when the browser blocks it. The store is
 * read at failure time, so no chip subscribes to it (a report can carry 277
 * of them).
 */
export function citedFileFailed(err?: unknown): void {
  useJobStore
    .getState()
    .pushToast(
      'error',
      err instanceof TabBlockedError
        ? TAB_BLOCKED_MESSAGE
        : 'Could not fetch the cited file. It may have been removed from your library.',
    );
}
