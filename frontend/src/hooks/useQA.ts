import { useCallback, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api, { AUTH_TOKEN_KEY } from '../services/api';
import { qaApi } from '../services/qaApi';
import type { ClarifyRequest, QAExchange, QARequest } from '../types/qa';

export function useQAHistory(jobId: string | null) {
  return useQuery({
    queryKey: ['qaHistory', jobId],
    queryFn: () => qaApi.getHistory(jobId!),
    enabled: !!jobId,
  });
}

export function useAskQuestion(jobId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: QARequest) => qaApi.ask(jobId, data),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['qaHistory', jobId] }),
  });
}

export function useClarifyQuestion(jobId: string) {
  return useMutation({
    mutationFn: (data: ClarifyRequest) => qaApi.clarify(jobId, data),
  });
}

// ---------------------------------------------------------------------------
// Streaming Q&A (SSE) — POST /jobs/{id}/qa/stream
// ---------------------------------------------------------------------------

export type QAStreamStage =
  | 'retrieving'
  | 'refining'
  | 'formulating'
  | 'extracting_references';

const STREAM_STAGES: ReadonlyArray<QAStreamStage> = [
  'retrieving',
  'refining',
  'formulating',
  'extracting_references',
];

/** Thrown when the stream endpoint responds with a non-2xx status before
 *  any SSE payload — carries the HTTP status so callers can fall back to
 *  the non-streaming mutation on 404 (endpoint not deployed yet). */
export class QAStreamHttpError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'QAStreamHttpError';
    this.status = status;
  }
}

interface QAStreamEvent {
  type?: string;
  stage?: string;
  exchange?: QAExchange;
  detail?: string;
}

/**
 * Streaming variant of `useAskQuestion`. `askStreaming` POSTs to the SSE
 * endpoint and consumes `data: <json>` lines via ReadableStream +
 * TextDecoder, exposing the current pipeline stage as state. On the
 * terminal "complete" event the Q&A history cache is invalidated exactly
 * like the non-streaming mutation's onSuccess.
 *
 * The existing `useAskQuestion` mutation is intentionally left intact —
 * callers fall back to it when this throws `QAStreamHttpError` with
 * status 404 (stream endpoint not deployed).
 */
export function useAskQuestionStreaming(jobId: string) {
  const queryClient = useQueryClient();
  const [stage, setStage] = useState<QAStreamStage | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);

  const askStreaming = useCallback(
    async (data: QARequest): Promise<QAExchange> => {
      // Same base URL + token source as services/api.ts.
      const baseURL = api.defaults.baseURL ?? 'http://localhost:8000/api/v1';
      const token = localStorage.getItem(AUTH_TOKEN_KEY);
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (token) headers.Authorization = `Bearer ${token}`;

      setIsStreaming(true);
      setStage(null);
      try {
        const response = await fetch(`${baseURL}/jobs/${jobId}/qa/stream`, {
          method: 'POST',
          headers,
          body: JSON.stringify(data),
        });
        if (!response.ok || !response.body) {
          throw new QAStreamHttpError(
            response.status,
            `Q&A stream request failed with status ${response.status}`,
          );
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let exchange: QAExchange | null = null;
        let done = false;

        // Parses one SSE line. Returns 'done' for the [DONE] sentinel, the
        // exchange payload on the "complete" event, null otherwise. Stage
        // events update state as a side effect; error events throw.
        const parseFrame = (rawLine: string): 'done' | QAExchange | null => {
          const line = rawLine.trim();
          if (!line.startsWith('data:')) return null;
          const payload = line.slice('data:'.length).trim();
          if (payload === '[DONE]') return 'done';
          let event: QAStreamEvent;
          try {
            event = JSON.parse(payload) as QAStreamEvent;
          } catch {
            return null; // malformed frame — skip defensively
          }
          if (event.type === 'stage' && typeof event.stage === 'string') {
            if ((STREAM_STAGES as readonly string[]).includes(event.stage)) {
              setStage(event.stage as QAStreamStage);
            }
            return null;
          }
          if (event.type === 'complete' && event.exchange) return event.exchange;
          if (event.type === 'error') {
            throw new Error(event.detail || 'Q&A stream reported an error.');
          }
          return null;
        };

        while (!done) {
          const { value, done: readerDone } = await reader.read();
          if (readerDone) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines) {
            const result = parseFrame(line);
            if (result === 'done') {
              done = true;
              break;
            }
            if (result) exchange = result;
          }
        }
        // Flush any trailing bytes / final unterminated line.
        if (!done) {
          buffer += decoder.decode();
          if (buffer) {
            const result = parseFrame(buffer);
            if (result && result !== 'done') exchange = result;
          }
        }

        if (!exchange) {
          throw new Error('Q&A stream ended without a completed answer.');
        }
        queryClient.invalidateQueries({ queryKey: ['qaHistory', jobId] });
        return exchange;
      } finally {
        setIsStreaming(false);
        setStage(null);
      }
    },
    [jobId, queryClient],
  );

  return { askStreaming, stage, isStreaming };
}
