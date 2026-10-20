/**
 * S-1.18.2: a degraded status must not disable features that are healthy.
 * Before the fix any failing feature (say, vision) greyed out Q&A and reports.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useFeatureAvailable } from '../useFeatureAvailable';
import { useCapability } from '../useCapability';
import { useSystemStatusStore } from '../../stores/systemStatusStore';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

function Probe({ feature, capability }: { feature: string; capability: string }) {
  const available = useFeatureAvailable(feature);
  const enabled = useCapability(capability);
  return <span data-available={String(available)} data-capability={String(enabled)} />;
}

function read(feature: string, capability = 'visual_analysis_enabled') {
  act(() => root.render(<Probe feature={feature} capability={capability} />));
  const el = host.querySelector('span') as HTMLSpanElement;
  return { available: el.dataset.available === 'true', capability: el.dataset.capability === 'true' };
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
  useSystemStatusStore.setState({ llmStatus: 'unknown', unavailableFeatures: [], capabilities: null });
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('useFeatureAvailable', () => {
  it('stays available while ANOTHER feature is down', () => {
    useSystemStatusStore.setState({ llmStatus: 'degraded', unavailableFeatures: ['visual_analysis'] });
    expect(read('qa').available).toBe(true);
    expect(read('visual_analysis').available).toBe(false);
  });

  it('is unavailable when every model is down', () => {
    useSystemStatusStore.setState({ llmStatus: 'down', unavailableFeatures: [] });
    expect(read('qa').available).toBe(false);
  });

  it('fails safe before the first poll', () => {
    expect(read('qa').available).toBe(true);
  });
});

describe('useCapability', () => {
  it('is false until health answers, then follows it', () => {
    expect(read('qa').capability).toBe(false);
    useSystemStatusStore.getState().setCapabilities({ visual_analysis_enabled: true });
    expect(read('qa').capability).toBe(true);
  });
});
