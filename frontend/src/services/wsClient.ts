import type { WSNotificationMessage, WSProgressMessage } from '../types/ws';
import { AUTH_TOKEN_KEY } from './api';

type Callback = (msg: WSProgressMessage) => void;
type NotificationCallback = (msg: WSNotificationMessage) => void;

const NOTIFICATIONS_TOPIC = 'notifications';

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
 *
 * T-8.3.3.8: the same socket carries the signed-in user's new-notification
 * events (`subscribe` with `topic: "notifications"`); the server binds them
 * to the user the token names. A socket is opened with one sign-in's token:
 * `AuthProvider` calls `disconnect()` when the token goes away, and `connect()`
 * replaces a socket whose token is no longer the stored one, so a tab never
 * keeps the old identity. A session revoked from another device (T-5.4.19) or
 * a token that has expired (T-5.4.21) is closed by the server with code 1008,
 * after which this client does not reconnect: the token would be refused, and
 * the page's next HTTP call gets a 401 and signs out.
 */
/** What the server closes an open socket with when its session has ended. */
const SESSION_REVOKED_CLOSE_CODE = 1008;

export class WSClient {
  private ws: WebSocket | null = null;
  /** The token `ws` was opened with, so a new sign-in gets its own socket. */
  private socketToken: string | null = null;
  private subscriptions = new Map<string, Set<Callback>>();
  private notificationCallbacks = new Set<NotificationCallback>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private pingInterval: number | null = null;

  private static send(socket: WebSocket | null, data: string | object): void {
    if (socket?.readyState !== WebSocket.OPEN) return;
    socket.send(typeof data === 'string' ? data : JSON.stringify(data));
  }

  connect(): void {
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    const state = this.ws?.readyState;
    if (state === WebSocket.OPEN || state === WebSocket.CONNECTING) {
      if (this.socketToken === token) return;
      // Opened as someone else (or signed out since): drop it. Its close
      // handler sees it is no longer `this.ws` and schedules nothing.
      this.dropSocket();
    }

    const baseUrl = resolveWsUrl();
    // The one URL that still carries the JWT (T-8.8.1.5): the WebSocket API
    // cannot set an Authorization header on the handshake. Every HTTP file is
    // fetched with the header instead (services/apiFiles.ts).
    const url = token
      ? `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      : baseUrl;
    const socket = new WebSocket(url);
    this.ws = socket;
    this.socketToken = token;

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
      if (this.notificationCallbacks.size > 0) {
        WSClient.send(socket, { action: 'subscribe', topic: NOTIFICATIONS_TOPIC });
      }
      if (this.pingInterval) clearInterval(this.pingInterval);
      this.pingInterval = window.setInterval(() => WSClient.send(socket, 'ping'), 30000);
    };

    socket.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const msg = JSON.parse(event.data) as WSProgressMessage | WSNotificationMessage;
        if (msg.type === 'notification') {
          this.notificationCallbacks.forEach((cb) => cb(msg));
          return;
        }
        const callbacks = this.subscriptions.get(msg.job_id);
        callbacks?.forEach((cb) => cb(msg));
      } catch {
        // ignore non-JSON messages
      }
    };

    socket.onclose = (event) => {
      if (this.ws !== socket) return;
      if (this.pingInterval) clearInterval(this.pingInterval);
      this.pingInterval = null;
      this.ws = null;
      if (event?.code === SESSION_REVOKED_CLOSE_CODE) return;
      this.handleReconnect();
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  private dropSocket(): void {
    if (this.pingInterval) clearInterval(this.pingInterval);
    this.pingInterval = null;
    const socket = this.ws;
    this.ws = null;
    this.socketToken = null;
    socket?.close();
  }

  private handleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) return;
    if (this.subscriptions.size === 0 && this.notificationCallbacks.size === 0) return;

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
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

  /**
   * T-8.3.3.8: hear about the signed-in user's new notifications. The first
   * listener subscribes the socket, the last one to leave unsubscribes it.
   */
  subscribeNotifications(callback: NotificationCallback): () => void {
    const first = this.notificationCallbacks.size === 0;
    this.notificationCallbacks.add(callback);
    // An open socket gets the subscribe now; a connecting one sends it from
    // onopen (send is a no-op until then).
    this.connect();
    if (first) WSClient.send(this.ws, { action: 'subscribe', topic: NOTIFICATIONS_TOPIC });

    return () => {
      if (!this.notificationCallbacks.delete(callback)) return;
      if (this.notificationCallbacks.size === 0) {
        WSClient.send(this.ws, { action: 'unsubscribe', topic: NOTIFICATIONS_TOPIC });
      }
    };
  }

  /** Sign-out: close the socket and forget everything, a waiting reconnect included. */
  disconnect(): void {
    this.subscriptions.clear();
    this.notificationCallbacks.clear();
    if (this.reconnectTimer !== null) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.dropSocket();
  }
}

export const wsClient = new WSClient();
