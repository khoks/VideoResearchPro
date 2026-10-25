/**
 * T-5.2.9 / D-111: an honest pricing page. Reels, public report sharing,
 * team workspaces and data residency are marked as planned, never as
 * included; the daily LLM-token lines are gone (nothing enforces them);
 * the document caps stay advertised.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TIER_DESCRIPTORS, getTierDescriptor } from '../../../data/tiers';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock('../../../contexts/AuthContext', () => ({ useAuth: () => ({ isAuthenticated: false, token: null }) }));
vi.mock('../../../hooks/useMe', () => ({ useMe: () => ({ data: undefined }) }));

import { PricingPage } from '../PricingPage';

const PLANNED = /reels|public report sharing|team workspace|data residency/i;
const rows = TIER_DESCRIPTORS.flatMap((t) => t.features.map((f) => ({ tier: t.tier, ...f })));

describe('the tier rows', () => {
  it('mark the unbuilt features as planned, and only those', () => {
    const planned = rows.filter((r) => r.planned);
    expect(planned.map((r) => `${r.tier}: ${r.label}`)).toEqual([
      'pro: Reels',
      'pro: Public report sharing (signed URLs)',
      'studio: Team workspaces',
      'studio: Data residency selection',
    ]);
    expect(planned.every((r) => !r.included)).toBe(true);
  });

  it('never list an unbuilt feature as included', () => {
    expect(rows.filter((r) => r.included && PLANNED.test(r.label))).toEqual([]);
  });

  it('drop the daily token allowance', () => {
    expect(rows.filter((r) => /token/i.test(r.label))).toEqual([]);
  });

  it('keep the document caps', () => {
    const caps = (tier: 'free' | 'pro' | 'studio') =>
      getTierDescriptor(tier).features.filter((f) => f.included && /documents/i.test(f.label)).map((f) => f.label);
    expect(caps('free')).toEqual(['Up to 500 documents in your library']);
    expect(caps('pro')).toEqual(['Up to 5,000 documents']);
    expect(caps('studio')).toEqual(['Unlimited documents']);
  });
});

describe('PricingPage', () => {
  let host: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    host = document.createElement('div');
    document.body.appendChild(host);
    root = createRoot(host);
  });

  afterEach(() => {
    act(() => root.unmount());
    host.remove();
  });

  it('renders planned rows as planned, without a check mark', () => {
    act(() => root.render(<MemoryRouter><PricingPage /></MemoryRouter>));
    const planned = Array.from(host.querySelectorAll('li[data-planned]'));
    expect(planned.map((li) => li.textContent)).toEqual([
      '○Reels Planned',
      '○Public report sharing (signed URLs) Planned',
      '○Team workspaces Planned',
      '○Data residency selection Planned',
    ]);
    for (const li of planned) expect(li.textContent).not.toContain('✓');
    const text = host.textContent ?? '';
    expect(text).not.toMatch(/tokens \/ day/i);
    expect(text).toContain('Up to 5,000 documents');
    expect(text).toContain('Author Studio — books, sites, decks');
  });
});
