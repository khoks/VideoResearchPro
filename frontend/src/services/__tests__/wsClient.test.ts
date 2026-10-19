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
});
