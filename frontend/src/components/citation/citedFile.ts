import { useJobStore } from '../../stores/jobStore';

/**
 * The toast for a cited file the API would not hand over (T-8.8.1.5): a PDF
 * citation opens through `openApiLink`, which fetches with the header. The
 * store is read at failure time, so no chip subscribes to it (a report can
 * carry 277 of them).
 */
export function citedFileFailed(): void {
  useJobStore
    .getState()
    .pushToast('error', 'Could not fetch the cited file. It may have been removed from your library.');
}
