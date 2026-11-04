/**
 * `/account/security` at the page the router mounts, over a mocked HTTP
 * client: active sessions (this one marked, others revocable, sign out
 * everywhere else), two-step verification (set up with the key and setup
 * link, confirm, recovery codes once; turn off with a code), changing the
 * password (with "Forgot it?" for the reset), and recent account activity
 * (the account scope, paged). The menu links here.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { AuditLogEntry, SessionInfo } from '../../services/accountSecurityApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

type Call = (url: string, config?: unknown) => Promise<{ data: unknown }>;
const http = {
  get: vi.fn<Call>(),
  post: vi.fn<(url: string, body?: unknown) => Promise<{ data: unknown }>>(),
  delete: vi.fn<Call>(),
};
vi.mock('../../services/api', () => ({
  default: {
    get: (url: string, config?: unknown) => http.get(url, config),
    post: (url: string, body?: unknown) => http.post(url, body),
    delete: (url: string, config?: unknown) => http.delete(url, config),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));

import { AccountSecurityPage } from '../AccountSecurityPage';

const UA_CHROME_WIN = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const UA_FIREFOX_LINUX = 'Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0';

function session(over: Partial<SessionInfo>): SessionInfo {
  return {
    id: over.jti ?? 'id',
    jti: 'jti',
    created_at: '2026-11-03T09:00:00',
    last_used_at: '2026-11-03T09:30:00',
    revoked_at: null,
    ip_address: '203.0.113.7',
    user_agent: UA_CHROME_WIN,
    is_current: false,
    expires_at: '2026-11-04T09:00:00+00:00',
    active: true,
    ...over,
  };
}

let sessions: SessionInfo[];
let mfaEnabled: boolean;
let activity: AuditLogEntry[];

function entry(i: number, event = 'login_success'): AuditLogEntry {
  return {
    id: `a${i}`,
    event,
    ip_address: '203.0.113.7',
    user_agent: UA_CHROME_WIN,
    metadata_json: null,
    created_at: `2026-11-0${(i % 3) + 1}T10:00:00`,
  };
}

let host: HTMLDivElement;
let root: Root;

async function flush() {
  for (let i = 0; i < 6; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

let qc: QueryClient;

async function mount() {
  qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={['/account/security']}>
          <AccountSecurityPage />
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  await flush();
}

const buttons = () => Array.from(host.querySelectorAll('button'));
const button = (label: string) => {
  const b = buttons().find((x) => x.textContent?.trim() === label || x.getAttribute('aria-label') === label);
  if (!b) throw new Error(`no button "${label}" in: ${buttons().map((x) => x.textContent).join(' | ')}`);
  return b;
};
async function click(label: string) {
  await act(async () => button(label).click());
  await flush();
}
async function type(el: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value);
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
}
async function submit(form: Element | null) {
  await act(async () => {
    form!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();
}

beforeEach(() => {
  localStorage.clear();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  sessions = [
    session({ jti: 'cur', is_current: true, last_used_at: '2026-11-03T11:00:00' }),
    session({ jti: 'laptop', user_agent: UA_FIREFOX_LINUX, ip_address: '198.51.100.2' }),
    session({ jti: 'gone', revoked_at: '2026-11-02T10:00:00', active: false }),
    session({ jti: 'old', active: false }),
  ];
  mfaEnabled = false;
  activity = [entry(1), entry(2, 'login_failure')];
  http.get.mockReset();
  http.post.mockReset();
  http.delete.mockReset();
  http.get.mockImplementation(async (url, config) => {
    if (url === '/auth/sessions') return { data: sessions };
    if (url === '/auth/mfa/status') return { data: { enabled: mfaEnabled } };
    if (url === '/auth/audit-log') {
      const { limit, offset } = (config as { params: { limit: number; offset: number } }).params;
      return { data: activity.slice(offset, offset + limit) };
    }
    throw new Error(`unexpected GET ${url}`);
  });
  http.delete.mockImplementation(async (url) => {
    if (url === '/auth/sessions') {
      sessions = sessions.filter((s) => s.is_current);
      return { data: { revoked_count: 3 } };
    }
    if (url.startsWith('/auth/sessions/')) {
      const jti = decodeURIComponent(url.split('/').pop()!);
      sessions = sessions.map((s) => (s.jti === jti ? { ...s, active: false, revoked_at: '2026-11-03T12:00:00' } : s));
      return { data: { revoked: true } };
    }
    if (url === '/auth/mfa') {
      mfaEnabled = false;
      return { data: { disabled: true } };
    }
    throw new Error(`unexpected DELETE ${url}`);
  });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

describe('sessions', () => {
  it('lists the live sessions with this one first and marked, and no sign-out on it', async () => {
    await mount();
    const rows = Array.from(host.querySelectorAll('[data-session]'));
    expect(rows.map((r) => r.getAttribute('data-session'))).toEqual(['cur', 'laptop']);
    expect(rows[0].textContent).toContain('Chrome on Windows');
    expect(rows[0].textContent).toContain('This device');
    expect(rows[0].querySelector('button')).toBeNull();
    expect(rows[1].textContent).toContain('Firefox on Linux');
    expect(rows[1].textContent).toContain('198.51.100.2');
    expect(rows[1].textContent).not.toContain('This device');
  });

  it('signs one session out', async () => {
    await mount();
    await click('Sign out Firefox on Linux');
    expect(http.delete).toHaveBeenCalledWith('/auth/sessions/laptop', undefined);
    expect(Array.from(host.querySelectorAll('[data-session]')).map((r) => r.getAttribute('data-session'))).toEqual(['cur']);
    expect(host.textContent).toContain('Signed out Firefox on Linux.');
  });

  it('signs out everywhere else and keeps this session', async () => {
    await mount();
    await click('Sign out everywhere else');
    expect(http.delete).toHaveBeenCalledWith('/auth/sessions', { params: { keep_current: true } });
    expect(host.textContent).toContain('Signed out 1 other session. This one stays signed in.');
    expect(button('Sign out everywhere else').disabled).toBe(true);
  });

  it('falls back to "not revoked" for a server without the active flag', async () => {
    sessions = [
      session({ jti: 'cur', is_current: true, active: undefined, expires_at: undefined }),
      session({ jti: 'gone', revoked_at: '2026-11-02T10:00:00', active: undefined }),
    ];
    await mount();
    expect(Array.from(host.querySelectorAll('[data-session]')).map((r) => r.getAttribute('data-session'))).toEqual(['cur']);
  });
});

describe('two-step verification', () => {
  const SECRET = 'JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP';
  const URI = `otpauth://totp/Pratidhvani:me%40x.com?secret=${SECRET}&issuer=Pratidhvani`;
  const CODES = ['AAAA111111', 'BBBB222222', 'CCCC333333'];

  it('sets up with the key and setup link, confirms with a code, and shows the recovery codes once', async () => {
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    http.post.mockImplementation(async (url, body) => {
      if (url === '/auth/mfa/enroll') return { data: { secret: SECRET, provisioning_uri: URI } };
      if (url === '/auth/mfa/verify-enrollment') {
        expect(body).toEqual({ code: '123456' });
        mfaEnabled = true;
        return { data: { enabled: true, recovery_codes: CODES } };
      }
      throw new Error(url);
    });
    await mount();
    expect(host.textContent).toContain('Off');
    await click('Set up two-step verification');

    expect(host.querySelector('[data-secret]')!.textContent).toBe('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP');
    expect(host.querySelector('[data-uri]')!.textContent).toBe(URI);
    await click('Copy key');
    expect(writeText).toHaveBeenLastCalledWith(SECRET);
    await click('Copy setup link');
    expect(writeText).toHaveBeenLastCalledWith(URI);
    // The key is in this card's state only: nothing stored, nothing sent elsewhere.
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET);
    expect(http.get.mock.calls.some((c) => JSON.stringify(c).includes(SECRET))).toBe(false);

    const form = host.querySelector('form[aria-label="Set up two-step verification"]');
    await type(form!.querySelector('input')!, '123 456');
    await submit(form);

    const list = host.querySelector('ol[aria-label="Recovery codes"]')!;
    expect(Array.from(list.querySelectorAll('li')).map((li) => li.textContent)).toEqual(CODES);
    expect(host.textContent).toContain('they are not shown again');
    await click('Copy codes');
    expect(writeText).toHaveBeenLastCalledWith(CODES.join('\n'));

    await click('I have saved them');
    expect(host.querySelector('ol[aria-label="Recovery codes"]')).toBeNull();
    expect(host.querySelector('[data-secret]')).toBeNull();
    expect(host.textContent).toContain('Turn off two-step verification');
    expect(host.textContent).not.toContain(CODES[0]);
  });

  it('says when the confirming code is wrong and keeps the setup open', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/mfa/enroll') return { data: { secret: SECRET, provisioning_uri: URI } };
      throw Object.assign(new Error('400'), { isAxiosError: true, response: { status: 400, data: { detail: 'Invalid TOTP code' } } });
    });
    await mount();
    await click('Set up two-step verification');
    const form = host.querySelector('form[aria-label="Set up two-step verification"]');
    await type(form!.querySelector('input')!, '000000');
    await submit(form);
    expect(host.querySelector('[role="alert"]')!.textContent).toContain('That code did not match');
    expect(host.querySelector('[data-secret]')).not.toBeNull();
  });

  /** The status query's background refetch fails, e.g. on window focus. */
  async function failStatusRefetch() {
    const ok = http.get.getMockImplementation()!;
    http.get.mockImplementation(async (url, config) => {
      if (url === '/auth/mfa/status') throw Object.assign(new Error('502'), { isAxiosError: true, response: { status: 502 } });
      return ok(url, config);
    });
    await act(async () => {
      await qc.refetchQueries({ queryKey: ['auth', 'mfa'] });
    });
    await flush();
    expect(qc.getQueryState(['auth', 'mfa'])!.status).toBe('error');
  }

  it('keeps the recovery codes on screen when a status refetch fails', async () => {
    http.post.mockImplementation(async (url) => {
      if (url === '/auth/mfa/enroll') return { data: { secret: SECRET, provisioning_uri: URI } };
      mfaEnabled = true;
      return { data: { enabled: true, recovery_codes: CODES } };
    });
    await mount();
    await click('Set up two-step verification');
    const form = host.querySelector('form[aria-label="Set up two-step verification"]');
    await type(form!.querySelector('input')!, '123456');
    await submit(form);

    await failStatusRefetch();

    const list = host.querySelector('ol[aria-label="Recovery codes"]');
    expect(list, 'the codes are not shown again once this view goes').not.toBeNull();
    expect(Array.from(list!.querySelectorAll('li')).map((li) => li.textContent)).toEqual(CODES);
    expect(host.textContent).not.toContain('Could not read whether two-step verification is on');
    expect(button('I have saved them')).toBeTruthy();
  });

  it('keeps the setup key on screen when a status refetch fails', async () => {
    http.post.mockResolvedValue({ data: { secret: SECRET, provisioning_uri: URI } });
    await mount();
    await click('Set up two-step verification');

    await failStatusRefetch();

    expect(host.querySelector('[data-secret]')!.textContent).toBe('JBSW Y3DP EHPK 3PXP JBSW Y3DP EHPK 3PXP');
    expect(host.querySelector('form[aria-label="Set up two-step verification"]')).not.toBeNull();
  });

  it('says it cannot read the status when the first read fails', async () => {
    const ok = http.get.getMockImplementation()!;
    http.get.mockImplementation(async (url, config) => {
      if (url === '/auth/mfa/status') throw Object.assign(new Error('502'), { isAxiosError: true, response: { status: 502 } });
      return ok(url, config);
    });
    await mount();
    expect(host.textContent).toContain('Could not read whether two-step verification is on');
    expect(buttons().some((b) => b.textContent === 'Set up two-step verification')).toBe(false);
  });

  it('cancelling the setup drops the key', async () => {
    http.post.mockResolvedValue({ data: { secret: SECRET, provisioning_uri: URI } });
    await mount();
    await click('Set up two-step verification');
    await click('Cancel');
    expect(host.textContent).not.toContain('JBSW');
    expect(button('Set up two-step verification')).toBeTruthy();
  });

  it('turns off with a code', async () => {
    mfaEnabled = true;
    await mount();
    expect(host.textContent).toContain('On');
    await click('Turn off two-step verification');
    const form = host.querySelector('form[aria-label="Turn off two-step verification"]');
    await type(form!.querySelector('input')!, 'AAAA111111');
    await submit(form);
    expect(http.delete).toHaveBeenCalledWith('/auth/mfa', { data: { code: 'AAAA111111' } });
    expect(button('Set up two-step verification')).toBeTruthy();
  });
});

describe('password', () => {
  const form = () => host.querySelector('form[aria-label="Change your password"]') as HTMLFormElement;
  const fields = () => Array.from(form().querySelectorAll('input'));
  const alert = () => form().querySelector('[role="alert"]')?.textContent;
  const status = () => form().querySelector('[role="status"]')?.textContent;
  const refused = (code: number, detail: string) =>
    Object.assign(new Error(String(code)), { isAxiosError: true, response: { status: code, data: { detail } } });

  async function fill(current: string, next: string, again = next) {
    const [a, b, c] = fields();
    await type(a, current);
    await type(b, next);
    await type(c, again);
  }

  it('changes the password, reports the sessions it signed out, and clears the fields', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok', sessions_revoked: 2 } });
    await mount();
    await fill('old-password', 'brand-new-password');
    await submit(form());

    expect(http.post).toHaveBeenCalledWith('/auth/password/change', {
      current_password: 'old-password',
      new_password: 'brand-new-password',
    });
    expect(status()).toBe('Password changed. Signed out 2 other sessions; this one stays signed in.');
    expect(fields().map((i) => i.value)).toEqual(['', '', '']);
    expect(JSON.stringify({ ...localStorage })).not.toContain('brand-new-password');
  });

  it('says so when no other session was signed in', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok', sessions_revoked: 0 } });
    await mount();
    await fill('old-password', 'brand-new-password');
    await submit(form());
    expect(status()).toBe('Password changed.');
  });

  it('re-reads the sessions after a change', async () => {
    http.post.mockResolvedValue({ data: { message: 'ok', sessions_revoked: 1 } });
    await mount();
    const before = http.get.mock.calls.filter((c) => c[0] === '/auth/sessions').length;
    await fill('old-password', 'brand-new-password');
    await submit(form());
    expect(http.get.mock.calls.filter((c) => c[0] === '/auth/sessions').length).toBeGreaterThan(before);
  });

  it('checks the new password here before sending', async () => {
    await mount();
    await fill('old-password', 'brand-new-password', 'something-else');
    await submit(form());
    expect(alert()).toContain('do not match');
    await fill('old-password', 'short');
    await submit(form());
    expect(alert()).toContain('at least 8 characters');
    expect(http.post).not.toHaveBeenCalled();
  });

  it('shows the refusal where the reader typed, and keeps what they typed', async () => {
    http.post.mockRejectedValue(refused(400, 'The current password is not right.'));
    await mount();
    await fill('wrong-password', 'brand-new-password');
    await submit(form());
    expect(alert()).toBe('The current password is not right.');
    expect(fields()[0].value).toBe('wrong-password');
    expect(status()).toBeUndefined();
  });

  it('passes on the pointer to the reset for an account with no password', async () => {
    const detail = 'This account has no password yet: it was made by signing in with Google or GitHub. To set one, use "Forgot it?" to get a reset code.';
    http.post.mockRejectedValue(refused(400, detail));
    await mount();
    await fill('anything-at-all', 'brand-new-password');
    await submit(form());
    expect(alert()).toBe(detail);
  });

  it('shows the lockout and rate-limit answers', async () => {
    http.post.mockRejectedValue(refused(429, 'Too many wrong passwords: password sign-in is locked for a while.'));
    await mount();
    await fill('old-password', 'brand-new-password');
    await submit(form());
    expect(alert()).toContain('Too many wrong passwords');
  });

  it('keeps the reset as "Forgot it?", in place of the old link', async () => {
    await mount();
    const forgot = Array.from(form().querySelectorAll('a')).find((a) => a.textContent === 'Forgot it?');
    expect(forgot?.getAttribute('href')).toBe('/forgot-password');
    expect(host.textContent).not.toContain('Reset your password');
  });

  it('uses the browser password fields, so a manager can fill and update them', async () => {
    await mount();
    expect(fields().map((i) => [i.type, i.autocomplete])).toEqual([
      ['password', 'current-password'],
      ['password', 'new-password'],
      ['password', 'new-password'],
    ]);
  });
});

describe('recent activity', () => {
  it('asks for the account scope, newest first, and pages', async () => {
    activity = Array.from({ length: 25 }, (_, i) => entry(i));
    activity[0] = { ...entry(0, 'login_failure'), metadata_json: JSON.stringify({ email: 'me@x.com' }) };
    await mount();
    const first = http.get.mock.calls.find((c) => c[0] === '/auth/audit-log')!;
    expect(first[1]).toEqual({ params: { scope: 'account', limit: 21, offset: 0 } });
    const rows = () => Array.from(host.querySelectorAll('ol[aria-label="Account activity"] li'));
    expect(rows()).toHaveLength(20);
    expect(rows()[0].textContent).toContain('Failed sign-in attempt');
    expect(button('Newer').disabled).toBe(true);

    await click('Older');
    const last = http.get.mock.calls.filter((c) => c[0] === '/auth/audit-log').pop()!;
    expect(last[1]).toEqual({ params: { scope: 'account', limit: 21, offset: 20 } });
    expect(rows()).toHaveLength(5);
    expect(button('Older').disabled).toBe(true);
    expect(host.textContent).toContain('Page 2');
  });

  it('has no pager when everything fits', async () => {
    await mount();
    expect(buttons().some((b) => b.textContent === 'Older')).toBe(false);
  });
});

describe('the account menu', () => {
  it('links to the security page', () => {
    const src = Object.values(
      import.meta.glob('../../layouts/AppLayout.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>,
    )[0];
    expect(src).toContain("onNavigatePath('/account/security')");
  });
});
