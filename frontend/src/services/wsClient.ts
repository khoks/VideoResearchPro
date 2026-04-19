import type { WSProgressMessage } from '../types/ws';
import { AUTH_TOKEN_KEY } from './api';

type Callback = (msg: WSProgressMessage) => void;

function resolveWsUrl(): string {
  const fromEnv = import.meta.env.VITE_WS_URL;
  if (fromEnv) return fromEnv;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/ws/jobs`;
}

class WSClient {
  private ws: WebSocket | null = null;
  private subscriptions = new Map<string, Set<Callback>>();
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private reconnectDelay = 1000;
  private pingInterval: number | null = null;

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const baseUrl = resolveWsUrl();
    const token = localStorage.getItem(AUTH_TOKEN_KEY);
    const url = token
      ? `${baseUrl}${baseUrl.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
      : baseUrl;
    this.ws = new WebSocket(url);

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.reconnectDelay = 1000;
      // Re-subscribe to all active subscriptions
      for (const jobId of this.subscriptions.keys()) {
        this.ws?.send(JSON.stringify({ action: 'subscribe', job_id: jobId }));
      }
      // Start ping interval
      this.pingInterval = window.setInterval(() => {
        this.ws?.send('ping');
      }, 30000);
    };

    this.ws.onmessage = (event) => {
      if (event.data === 'pong') return;
      try {
        const msg: WSProgressMessage = JSON.parse(event.data);
        const callbacks = this.subscriptions.get(msg.job_id);
        callbacks?.forEach((cb) => cb(msg));
      } catch {
        // ignore non-JSON messages
      }
    };

    this.ws.onclose = () => {
      if (this.pingInterval) clearInterval(this.pingInterval);
      this.handleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
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

    // Connect if not already
    this.connect();

    // Send subscribe message
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: 'subscribe', job_id: jobId }));
    }

    // Return unsubscribe function
    return () => {
      const callbacks = this.subscriptions.get(jobId);
      callbacks?.delete(callback);
      if (callbacks?.size === 0) {
        this.subscriptions.delete(jobId);
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: 'unsubscribe', job_id: jobId }));
        }
      }
    };
  }

  disconnect(): void {
    if (this.pingInterval) clearInterval(this.pingInterval);
    this.subscriptions.clear();
    this.ws?.close();
    this.ws = null;
  }
}

export const wsClient = new WSClient();
