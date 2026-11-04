/**
 * T-8.3.3.8: the bell opens the shared socket on every signed-in page, so
 * signing out has to close it. The auth context does, on every way a token
 * goes away: nothing in the layout can, because the layout unmounts with the
 * sign-in and only drops its listener. Uses the real wsClient over a fake
 * WebSocket.
 */
import { act, useEffect } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider, useAuth } from '../AuthContext';
import { wsClient } from '../../services/wsClient';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TOKEN_KEY = 'videoresearchpro.authToken';

const postMock = vi.fn();
vi.mock('../../services/api', () => ({
  default: {
    post: (...a: unknown[]) => postMock(...a),
    get: vi.fn(),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
  },
  AUTH_TOKEN_KEY: 'videoresearchpro.authToken',
}));

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readyState = FakeWebSocket.CONNECTING;
  sent: string[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

let host: HTMLDivElement;
let root: Root;
let ctx: ReturnType<typeof useAuth>;

function Probe() {
  const value = useAuth();
  useEffect(() => {
    ctx = value;
  });
  return null;
}

function openBell() {
  const leave = wsClient.subscribeNotifications(() => {});
  const socket = FakeWebSocket.instances.at(-1)!;
  socket.open();
  return { leave, socket };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval'] });
  localStorage.clear();
  localStorage.setItem(TOKEN_KEY, 'token-a');
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => root.render(<AuthProvider><Probe /></AuthProvider>));
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  wsClient.disconnect();
  postMock.mockReset();
  localStorage.clear();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the socket and the sign-in', () => {
  it('a sign-out closes the socket, and nothing reopens it', async () => {
    const { socket } = openBell();
    expect(socket.url).toContain('token=token-a');
    postMock.mockResolvedValueOnce({});

    await act(async () => {
      await ctx.logout();
    });

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    vi.advanceTimersByTime(120_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('closes it even when the listener already left with the layout', async () => {
    const { leave, socket } = openBell();
    leave();
    postMock.mockResolvedValueOnce({});
    await act(async () => {
      await ctx.logout();
    });
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it('a failed revoke still closes it', async () => {
    const { socket } = openBell();
    postMock.mockRejectedValueOnce(new Error('offline'));
    await act(async () => {
      await ctx.logout();
    });
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it('a sign-out in another tab closes this tab’s socket too', () => {
    const { socket } = openBell();
    act(() => {
      localStorage.removeItem(TOKEN_KEY);
      window.dispatchEvent(new StorageEvent('storage', { key: TOKEN_KEY, newValue: null }));
    });
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    vi.advanceTimersByTime(120_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('leaves the socket alone while the sign-in stands', () => {
    const { socket } = openBell();
    act(() => {
      window.dispatchEvent(new StorageEvent('storage', { key: 'something-else', newValue: 'x' }));
    });
    expect(socket.readyState).toBe(FakeWebSocket.OPEN);
  });
});
