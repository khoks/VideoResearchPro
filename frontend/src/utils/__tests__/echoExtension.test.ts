import { describe, expect, it } from 'vitest';
import { apiOrigin, lastUsedLabel } from '../echoExtension';

describe('apiOrigin', () => {
  it('uses the API host when the base URL is absolute (development)', () => {
    expect(apiOrigin('http://localhost:8000/api/v1', 'http://localhost:5173')).toBe('http://localhost:8000');
  });

  it('uses the app origin when the base URL is relative (production)', () => {
    expect(apiOrigin('/api/v1', 'https://echo.example.com')).toBe('https://echo.example.com');
    expect(apiOrigin(undefined, 'https://echo.example.com')).toBe('https://echo.example.com');
  });
});

describe('lastUsedLabel', () => {
  const now = new Date('2026-10-19T12:00:00Z');
  it('reads naturally across minutes, hours and days', () => {
    expect(lastUsedLabel(null, now)).toBe('Never used');
    expect(lastUsedLabel('2026-10-19T11:59:30Z', now)).toBe('Used just now');
    expect(lastUsedLabel('2026-10-19T11:15:00Z', now)).toBe('Used 45 minutes ago');
    expect(lastUsedLabel('2026-10-19T11:00:00Z', now)).toBe('Used 1 hour ago');
    expect(lastUsedLabel('2026-10-16T12:00:00Z', now)).toBe('Used 3 days ago');
  });
});
