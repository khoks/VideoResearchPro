/**
 * T-5.4.20: the OAuth return page starts the exchange only once the router has
 * committed the clean address, because the page to return to travels in that
 * address's state. `PublicOnlyRoute` reads it the moment a token appears, so a
 * token that beat the commit would send the reader to `/`.
 *
 * A real exchange takes longer than the commit, so the flow tests cannot lose
 * this race. Here the commit is held back until the test lets it through.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const { held, completeOAuth } = vi.hoisted(() => ({
  held: { navigate: null as unknown as (to: string, options: unknown) => void },
  completeOAuth: async (..._args: string[]) => ({ status: 'signed_in' }),
}));
const exchange = vi.fn(completeOAuth);

vi.mock('react-router-dom', async (orig) => ({
  ...(await orig<typeof import('react-router-dom')>()),
  useNavigate: () => held.navigate,
}));
vi.mock('../../contexts/AuthContext', () => ({ useAuth: () => ({ completeOAuth: exchange }) }));

import { OAuthCallbackPage } from '../OAuthCallbackPage';

const CALLBACK = '/login/oauth/google/callback';

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  sessionStorage.clear();
  sessionStorage.setItem('pratidhvani.signInReturn', '/jobs/run-1');
  exchange.mockClear();
  held.navigate = vi.fn();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('the OAuth return page', () => {
  it('waits for the clean address before it exchanges the code', async () => {
    const router = createMemoryRouter([{ path: '/login/oauth/:provider/callback', element: <OAuthCallbackPage /> }], {
      initialEntries: [`${CALLBACK}?code=abc&state=xyz`],
    });
    await act(async () => {
      root.render(<RouterProvider router={router} />);
    });

    expect(held.navigate).toHaveBeenCalledExactlyOnceWith(CALLBACK, { replace: true, state: { from: '/jobs/run-1' } });
    expect(exchange, 'the address still carries the code').not.toHaveBeenCalled();

    await act(async () => {
      await router.navigate(CALLBACK, { replace: true, state: { from: '/jobs/run-1' } });
    });
    expect(exchange).toHaveBeenCalledExactlyOnceWith('google', 'abc', 'xyz');

    await act(async () => {
      await router.navigate(CALLBACK, { replace: true, state: { from: '/jobs/run-1' } });
    });
    expect(exchange, 'the code is single-use').toHaveBeenCalledTimes(1);
  });
});
