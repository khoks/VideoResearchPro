import type { WSProgressMessage } from '../types/ws';
import { AUTH_TOKEN_KEY } from './api';

type Callback = (msg: WSProgressMessage) => void;

function resolveWsUrl(): string {
  const fromEnv = import.meta.env.VITE_WS_URL;
  if (fromEnv) return fromEnv;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/jobs`;
}

/**
 * One multiplexed socket for job and Author output progress (both publish on
 * `job_progress:{id}`; the server checks the caller owns the id).
 *
 * T-6.7.1.6: `connect()` used to skip only an OPEN socket, so a second
 * subscribe while the first socket was still CONNECTING (React StrictMode
 * mounts effects twice) opened a second socket and overwrote `this.ws`. The
 * first socket's `onopen` then sent on the replacement, which was still
 * connecting: `InvalidStateError: Still in CONNECTING state`. Now a
 * connecting socket is reused, every handler talks to the socket it belongs
 * to, and a replaced socket's close never schedules a reconnect.
 */
export class WSClient {
  private ws: WebSocket | null = null;
  private subscriptions = new Map<string, Set<Callback>>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  private pingInterval: number | null = null;

  private static send(socket: WebSocket | null, data: string | object): void {
    if (socket?.readyState !== WebSocket.OPEN) return;
    socket.send(typeof data === 'string' ? data : JSON.stringify(data));
  }

  connect(): void {
    const state = this.ws?.readyState;
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) return;

    const baseUrl = resolveWsUrl();
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    // The one URL that still carries the JWT (T-8.8.1.5): the WebSocket API
    // cannot set an Authorization header on the handshake. Every HTTP file is
    // fetched with the header instead (services/apiFiles.ts).
    const url = token
      ? `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      : baseUrl;
    const socket = new WebSocket(url);
    this.ws = socket;

    socket.onopen = () => {
      if (this.ws !== socket) {
        socket.close();
        return;
      }
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      // Re-subscribe to all active subscriptions
      for (const jobId of this.subscriptions.keys()) {
        WSClient.send(socket, { action: 'subscribe', job_id: jobId });
      }
      if (this.pingInterval) clearInterval(this.pingInterval);
      this.pingInterval = window.setInterval(() => WSClient.send(socket, 'ping'), 30000);
    };

    socket.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const msg: WSProgressMessage = JSON.parse(event.data);
        const callbacks = this.subscriptions.get(msg.job_id);
        callbacks?.forEach((cb) => cb(msg));
      } catch {
        // ignore non-JSON messages
      }
    };

    socket.onclose = () => {
      if (this.ws !== socket) return;
      if (this.pingInterval) clearInterval(this.pingInterval);
      this.pingInterval = null;
      this.ws = null;
      this.handleReconnect();
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  private handleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    if (this.subscriptions.size === 0) return;

    setTimeout(() => {
      this.reconnectAttempts++;
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, 30000);
      this.connect();
    }, this.reconnectDelay);
  }

  subscribe(jobId: string, callback: Callback): () => void {
    if (!this.subscriptions.has(jobId)) {
      this.subscriptions.set(jobId, new Set());
    }
    this.subscriptions.get(jobId)!.add(callback);

    // Connect if not already; an open socket gets the subscribe now, a
    // connecting one sends it from onopen.
    this.connect();
    WSClient.send(this.ws, { action: 'subscribe', job_id: jobId });

    // Return unsubscribe function
    return () => {
      const callbacks = this.subscriptions.get(jobId);
      callbacks?.delete(callback);
      if (callbacks?.size === 0) {
        this.subscriptions.delete(jobId);
        WSClient.send(this.ws, { action: 'unsubscribe', job_id: jobId });
      }
    };
  }

  disconnect(): void {
    if (this.pingInterval) clearInterval(this.pingInterval);
    this.pingInterval = null;
    this.subscriptions.clear();
    const socket = this.ws;
    this.ws = null;
    socket?.close();
  }
}

export const wsClient = new WSClient();
