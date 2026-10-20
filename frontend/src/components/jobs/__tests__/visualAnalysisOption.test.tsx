/** S-1.18.2 (T-1.18.2.1): the per-run visual-analysis opt-in. */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VisualAnalysisOption } from '../VisualAnalysisOption';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;

function mount(props: Partial<Parameters<typeof VisualAnalysisOption>[0]> = {}) {
  const onChange = vi.fn();
  act(() =>
    root.render(
      <VisualAnalysisOption checked={false} onChange={onChange} installEnabled modelsAvailable {...props} />,
    ),
  );
  return { onChange, box: host.querySelector('input[type="checkbox"]') as HTMLInputElement };
}

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

describe('VisualAnalysisOption', () => {
  it('turns on and off when the install and models allow it', () => {
    const { onChange, box } = mount();
    expect(box.disabled).toBe(false);
    act(() => box.click());
    expect(onChange).toHaveBeenCalledWith(true);
    expect(host.textContent).toContain('$0.20');
  });

  it('is disabled with the reason when the install switch is off', () => {
    const { box } = mount({ installEnabled: false });
    expect(box.disabled).toBe(true);
    expect(host.textContent).toContain('VISUAL_ENABLED');
  });

  it('is disabled with the reason when the vision models are down', () => {
    const { box } = mount({ modelsAvailable: false });
    expect(box.disabled).toBe(true);
    expect(host.textContent).toContain('startup check');
  });

  it('tells a carried-over run it will go without frames, and offers to turn it off', () => {
    const { onChange, box } = mount({ checked: true, installEnabled: false });
    expect(box.checked).toBe(false);
    expect(host.textContent).toContain('will run without frames');
    const turnOff = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Turn off') as HTMLButtonElement;
    act(() => turnOff.click());
    expect(onChange).toHaveBeenCalledWith(false);
  });
});
