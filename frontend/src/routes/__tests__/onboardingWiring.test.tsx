/**
 * S-8.10.1 wiring: the gate and the wizard are the routes the app actually
 * mounts, and a new registration lands on `/` (the gate) rather than
 * skipping it. These fail if the pieces exist but nothing reaches them.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import type { RouteObject } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { OnboardingGate } from '../../components/onboarding/OnboardingGate';
import { WelcomePage } from '../../pages/WelcomePage';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const registerMock = vi.fn(async () => undefined);
vi.mock('../../contexts/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, isLoading: false, register: registerMock, login: vi.fn() }),
}));

function find(routes: RouteObject[], pred: (r: RouteObject) => boolean): RouteObject | undefined {
  for (const r of routes) {
    if (pred(r)) return r;
    const hit = r.children ? find(r.children, pred) : undefined;
    if (hit) return hit;
  }
  return undefined;
}

describe('routes', () => {
  it('mounts the gate at the app index and the wizard at /welcome', async () => {
    const { router } = await import('../index');
    const app = find(router.routes, (r) => r.path === '/' && !!r.children);
    expect(app).toBeTruthy();
    const index = app!.children!.find((r) => r.index);
    expect((index?.element as { type?: unknown })?.type).toBe(OnboardingGate);
    const welcome = app!.children!.find((r) => r.path === 'welcome');
    expect((welcome?.element as { type?: unknown })?.type).toBe(WelcomePage);
  });
});

function Where() {
  return <output data-where>{useLocation().pathname}</output>;
}

describe('RegisterPage', () => {
  let host: HTMLDivElement;
  let root: Root;
  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });
  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it('sends a new account to / so the gate can open the wizard', async () => {
    const { RegisterPage } = await import('../../pages/RegisterPage');
    act(() =>
      root.render(
        <MemoryRouter initialEntries={['/register']}>
          <Routes>
            <Route path="/register" element={<RegisterPage />} />
            <Route path="*" element={null} />
          </Routes>
          <Where />
        </MemoryRouter>,
      ),
    );
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    const [email, password, confirm] = Array.from(host.querySelectorAll('input'));
    act(() => {
      for (const [el, v] of [[email, 'new@example.com'], [password, 'longenough1'], [confirm, 'longenough1']] as const) {
        setter.call(el, v);
        el.dispatchEvent(new Event('input', { bubbles: true }));
      }
    });
    await act(async () => {
      host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    });
    expect(registerMock).toHaveBeenCalled();
    expect(host.querySelector('[data-where]')?.textContent).toBe('/');
  });
});
