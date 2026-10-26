/**
 * T-5.2.10: the document cap's refusal reaches the user as its `message`
 * (the detail is an object, unlike most errors), and the Subscription page
 * reads the `documents` usage the server derives from the library.
 */
import { AxiosError, AxiosHeaders } from 'axios';
import { describe, expect, it } from 'vitest';
import { apiErrorMessage } from '../apiError';
import { describeUploadError, detailFromErrorBody } from '../ingestResults';
import { documentUsageLine } from '../documentCap';
import type { QuotaResponse } from '../../services/quotaApi';

const MESSAGE = "Your library is at the Free plan's cap of 500 documents. This PDF is not in your library yet.";

function quotaBody(message: string | null = MESSAGE) {
  return {
    detail: {
      error: 'quota_exceeded',
      resource: 'documents',
      consumed: 500,
      limit: 500,
      requested: 1,
      available: 0,
      retry_at: null,
      retry_after_sec: null,
      ...(message === null ? {} : { message }),
    },
  };
}

function axios429(data: unknown): AxiosError {
  const headers = new AxiosHeaders();
  return new AxiosError('Request failed with status code 429', 'ERR_BAD_REQUEST', undefined, undefined, {
    status: 429,
    statusText: 'Too Many Requests',
    headers,
    config: { headers },
    data,
  });
}

function quota(consumed: number, limit: number): QuotaResponse {
  return {
    tier: 'free',
    resources: [
      { resource: 'qa_exchanges', period_kind: 'monthly', period_start: '', period_end: null, consumed: 1, limit: 50, over_limit: false },
      { resource: 'documents', period_kind: 'lifetime', period_start: '', period_end: null, consumed, limit, over_limit: limit >= 0 && consumed >= limit },
    ],
  };
}

describe('reading an object-shaped detail', () => {
  it('apiErrorMessage returns detail.message', () => {
    expect(apiErrorMessage(axios429(quotaBody()), 'fallback')).toBe(MESSAGE);
  });

  it('apiErrorMessage falls back when the object has no message', () => {
    expect(apiErrorMessage(axios429(quotaBody(null)), 'fallback')).toBe('fallback');
  });

  it('apiErrorMessage still reads string details and pydantic lists', () => {
    expect(apiErrorMessage(axios429({ detail: 'plain' }), 'fallback')).toBe('plain');
    expect(apiErrorMessage(axios429({ detail: [{ msg: 'Value error, bad' }] }), 'fallback')).toBe('bad');
  });

  it('detailFromErrorBody returns detail.message (the paste form shows it)', () => {
    expect(detailFromErrorBody(quotaBody())).toBe(MESSAGE);
    expect(detailFromErrorBody(quotaBody(null))).toBeNull();
    expect(detailFromErrorBody({ detail: 'plain' })).toBe('plain');
  });

  it('describeUploadError shows the cap message on a 429, with a fallback', () => {
    expect(describeUploadError({ response: { status: 429, data: quotaBody() } })).toBe(MESSAGE);
    expect(describeUploadError({ response: { status: 429, data: {} } })).toMatch(/document cap/);
  });
});

describe('documentUsageLine', () => {
  it('is null until the quota has loaded or without a documents row', () => {
    expect(documentUsageLine(undefined)).toBeNull();
    expect(documentUsageLine({ tier: 'free', resources: [] })).toBeNull();
  });

  it('reads usage under the cap', () => {
    expect(documentUsageLine(quota(312, 500))).toBe('Your library holds 312 documents of the 500 this plan allows.');
    expect(documentUsageLine(quota(1, 5000))).toBe('Your library holds 1 document of the 5,000 this plan allows.');
  });

  it('says when the library is full or over the cap', () => {
    expect(documentUsageLine(quota(500, 500))).toBe("Your library is at this plan's cap of 500 documents. Nothing new can be added.");
    expect(documentUsageLine(quota(3000, 500))).toBe(
      "Your library holds 3,000 documents, over this plan's cap of 500. Everything stays, but nothing new can be added.",
    );
  });

  it('says there is no cap on an unlimited plan', () => {
    expect(documentUsageLine(quota(12000, -1))).toBe('Your library holds 12,000 documents. This plan has no document cap.');
  });
});
