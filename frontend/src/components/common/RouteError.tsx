/**
 * What the app shows when a page throws while it renders (T-4.11.2.3).
 *
 * Set as the root route's `errorElement`, so it covers every route with no
 * closer one: the marketing and sign-in pages, the app layout, and every
 * eagerly bundled page. Without it React Router shows its default screen,
 * with the error and its stack. A lazy route keeps its own `RouteLoadError`,
 * inside the layout, because a chunk that cannot load has a different cause.
 *
 * The error itself goes to the console, where React Router reports it. Nothing
 * from it reaches the screen.
 */
import { useNavigate } from 'react-router-dom';
import { Button, EmptyState } from '../primitives';
import { measure, space } from '../../theme';

export function RouteError() {
  const navigate = useNavigate();
  return (
    <div
      style={{
        minHeight: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: space['5'],
      }}
    >
      <EmptyState
        title="This page slipped off the shelf."
        description="Something went wrong while opening it. Your library is safe. Go back to it, or reload this page to try again."
        style={{ maxWidth: measure.form, width: '100%' }}
        action={
          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'center', gap: space['2'] }}>
            <Button size="sm" onClick={() => navigate('/library')}>
              Back to your library
            </Button>
            <Button size="sm" variant="secondary" onClick={() => window.location.reload()}>
              Reload
            </Button>
          </div>
        }
      />
    </div>
  );
}
