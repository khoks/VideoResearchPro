/**
 * What a lazy route shows when its code cannot be loaded (T-8.8.4.1).
 *
 * A route's chunk is fetched when the reader opens it, so it can fail where
 * an eagerly bundled page cannot: the dev server is mid-restart
 * (`POST /admin/restart`, `scripts/restart_services.ps1`), or a redeploy
 * replaced the chunk this tab knows by hash. React.lazy caches the rejected
 * import, so the route stays broken in that tab even after the server is
 * back, and only a full reload recovers it. Without this, React Router shows
 * its default error screen with a stack trace.
 *
 * Set as the route's `errorElement`, so it renders inside the app layout and
 * the sidebar still works. It also catches a render error in the page.
 */
import { Button, EmptyState } from '../primitives';

export function RouteLoadError() {
  return (
    <EmptyState
      title="This page could not be loaded"
      description="The app may have restarted or updated since this tab opened. Reloading usually fixes it."
      action={
        <Button size="sm" variant="secondary" onClick={() => window.location.reload()}>
          Reload
        </Button>
      }
    />
  );
}
