import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/** A WebSocket stand-in that only changes state when the test says so. */
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
    if (this.readyState !== FakeWebSocket.OPEN) {
      // What the browser does: the bug this suite pins.
      throw new Error("InvalidStateError: Failed to execute 'send' on 'WebSocket': Still in CONNECTING state.");
    }
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

describe('WSClient (T-6.7.1.6)', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  async function freshClient() {
    const { WSClient } = await import('../wsClient');
    return new WSClient();
  }

  it('reuses a connecting socket instead of opening a second one', async () => {
    const client = await freshClient();
    client.subscribe('job-a', () => {});
    client.subscribe('output-b', () => {});
    expect(FakeWebSocket.instances).toHaveLength(1);

    expect(() => FakeWebSocket.instances[0].open()).not.toThrow();
    expect(FakeWebSocket.instances[0].sent.map((s) => JSON.parse(s))).toEqual([
      { action: 'subscribe', job_id: 'job-a' },
      { action: 'subscribe', job_id: 'output-b' },
    ]);
  });

  it('sends a subscribe straight away once the socket is open', async () => {
    const client = await freshClient();
    client.subscribe('a', () => {});
    const socket = FakeWebSocket.instances[0];
    socket.open();
    client.subscribe('b', () => {});
    expect(socket.sent.map((s) => JSON.parse(s).job_id)).toEqual(['a', 'b']);
  });

  it('routes messages to the matching subscription and unsubscribes cleanly', async () => {
    const client = await freshClient();
    const seen: string[] = [];
    const unsubscribe = client.subscribe('out-1', (m) => seen.push(m.message ?? ''));
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.onmessage?.({ data: JSON.stringify({ type: 'job_progress', job_id: 'out-1', message: 'Chapter 1 of 2', timestamp: '' }) });
    socket.onmessage?.({ data: JSON.stringify({ type: 'job_progress', job_id: 'other', message: 'nope', timestamp: '' }) });
    expect(seen).toEqual(['Chapter 1 of 2']);

    unsubscribe();
    expect(JSON.parse(socket.sent.at(-1)!)).toEqual({ action: 'unsubscribe', job_id: 'out-1' });
  });

  it('never pings or subscribes on a socket that is not open', async () => {
    const client = await freshClient();
    client.subscribe('a', () => {});
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.readyState = FakeWebSocket.CLOSING;
    expect(() => vi.advanceTimersByTime(31_000)).not.toThrow();
    expect(() => client.subscribe('b', () => {})).not.toThrow();
  });

  it('reconnects after the current socket closes, and resubscribes', async () => {
    const client = await freshClient();
    client.subscribe('a', () => {});
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].close();
    vi.advanceTimersByTime(1_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
    FakeWebSocket.instances[1].open();
    expect(JSON.parse(FakeWebSocket.instances[1].sent[0])).toEqual({ action: 'subscribe', job_id: 'a' });
  });

  it('disconnect does not schedule a reconnect', async () => {
    const client = await freshClient();
    client.subscribe('a', () => {});
    FakeWebSocket.instances[0].open();
    client.disconnect();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it('disconnect cancels a reconnect that was already waiting', async () => {
    const client = await freshClient();
    client.subscribe('a', () => {});
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].close();
    client.disconnect();
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});

describe('WSClient notifications (T-8.3.3.8)', () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal('WebSocket', FakeWebSocket);
    vi.useFakeTimers();
    window.localStorage.setItem('videoresearchpro.authToken', 'token-a');
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    window.localStorage.removeItem('videoresearchpro.authToken');
  });

  async function freshClient() {
    const { WSClient } = await import('../wsClient');
    return new WSClient();
  }

  const sent = (socket: FakeWebSocket) => socket.sent.map((s) => JSON.parse(s));
  const NOTIFY = { action: 'subscribe', topic: 'notifications' };

  it('subscribes to the notifications once, on open or at once', async () => {
    const client = await freshClient();
    client.subscribeNotifications(() => {});
    client.subscribeNotifications(() => {});
    const socket = FakeWebSocket.instances[0];
    expect(FakeWebSocket.instances).toHaveLength(1);
    socket.open();
    expect(sent(socket)).toEqual([NOTIFY]);

    // A socket already open for a job gets the subscribe straight away.
    const other = await freshClient();
    other.subscribe('job-a', () => {});
    FakeWebSocket.instances[1].open();
    other.subscribeNotifications(() => {});
    expect(sent(FakeWebSocket.instances[1])).toEqual([{ action: 'subscribe', job_id: 'job-a' }, NOTIFY]);
  });

  it('routes a notification to the bell and never to a job', async () => {
    const client = await freshClient();
    const bell: string[] = [];
    const job: string[] = [];
    client.subscribeNotifications((m) => bell.push(m.id));
    client.subscribe('job-a', (m) => job.push(m.type));
    const socket = FakeWebSocket.instances[0];
    socket.open();
    socket.onmessage?.({ data: JSON.stringify({ type: 'notification', id: 'n1', kind: 'saved_search_changed', job_id: 'job-a' }) });
    socket.onmessage?.({ data: JSON.stringify({ type: 'job_progress', job_id: 'job-a', timestamp: '' }) });
    expect(bell).toEqual(['n1']);
    expect(job).toEqual(['job_progress']);
  });

  it('unsubscribes when the last listener leaves, and only then', async () => {
    const client = await freshClient();
    const leaveA = client.subscribeNotifications(() => {});
    const leaveB = client.subscribeNotifications(() => {});
    const socket = FakeWebSocket.instances[0];
    socket.open();
    leaveA();
    leaveA(); // twice is harmless
    expect(sent(socket)).toEqual([NOTIFY]);
    leaveB();
    expect(sent(socket)).toEqual([NOTIFY, { action: 'unsubscribe', topic: 'notifications' }]);
    socket.onmessage?.({ data: JSON.stringify({ type: 'notification', id: 'late' }) }); // nobody left to call
  });

  it('a dropped socket reconnects for the bell alone and resubscribes it', async () => {
    const client = await freshClient();
    client.subscribeNotifications(() => {});
    FakeWebSocket.instances[0].open();
    FakeWebSocket.instances[0].close();
    vi.advanceTimersByTime(1_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
    FakeWebSocket.instances[1].open();
    expect(sent(FakeWebSocket.instances[1])).toEqual([NOTIFY]);
  });

  it('a socket never outlives its sign-in: a new token opens a new socket', async () => {
    const client = await freshClient();
    const leave = client.subscribeNotifications(() => {});
    const first = FakeWebSocket.instances[0];
    expect(first.url).toContain('token=token-a');
    first.open();
    leave();

    window.localStorage.setItem('videoresearchpro.authToken', 'token-b');
    client.subscribeNotifications(() => {});
    expect(first.readyState).toBe(FakeWebSocket.CLOSED);
    expect(FakeWebSocket.instances).toHaveLength(2);
    const second = FakeWebSocket.instances[1];
    expect(second.url).toContain('token=token-b');
    second.open();
    expect(sent(second)).toEqual([NOTIFY]);

    // The replaced socket's close scheduled nothing.
    vi.advanceTimersByTime(60_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it('the same token keeps the socket it has', async () => {
    const client = await freshClient();
    client.subscribe('job-a', () => {});
    FakeWebSocket.instances[0].open();
    client.subscribeNotifications(() => {});
    expect(FakeWebSocket.instances).toHaveLength(1);
  });
});
