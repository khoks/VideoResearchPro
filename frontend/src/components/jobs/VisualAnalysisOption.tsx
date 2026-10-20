import { useId } from 'react';
import { Button } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

export interface VisualAnalysisOptionProps {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** VISUAL_ENABLED on this install (`/health` capabilities). */
  installEnabled: boolean;
  /** The vision models passed their startup probe. */
  modelsAvailable: boolean;
}

/**
 * S-1.18.2 (T-1.18.2.1): the per-run opt-in for visual analysis (R1, D-067).
 * Frame capture needs the install switch AND healthy vision models; when
 * either is missing the box is disabled and says why. A run or template that
 * carried the option over while it cannot run gets a plain notice instead of
 * a silently ignored setting.
 */
export function VisualAnalysisOption({ checked, onChange, installEnabled, modelsAvailable }: VisualAnalysisOptionProps) {
  const c = useColors();
  const id = useId();
  const usable = installEnabled && modelsAvailable;
  const reason = !installEnabled
    ? 'Visual analysis is turned off on this install (VISUAL_ENABLED).'
    : !modelsAvailable
      ? 'The vision models failed their startup check, so frames cannot be described right now.'
      : null;

  return (
    <div
      data-testid="visual-analysis-option"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: space['2'],
        background: checked && usable ? c.infoSubtle : c.surfaceAlt,
        border: `1px solid ${checked && usable ? c.info : c.border}`,
        borderRadius: radius.md,
        padding: `${space['3']} ${space['4']}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textPrimary,
        lineHeight: lineHeight.snug,
      }}
    >
      <label htmlFor={id} style={{ display: 'flex', gap: space['3'], alignItems: 'flex-start', cursor: usable ? 'pointer' : 'not-allowed' }}>
        <input
          id={id}
          type="checkbox"
          checked={checked && usable}
          disabled={!usable}
          onChange={(e) => onChange(e.target.checked)}
          style={{ marginTop: 3 }}
        />
        <span>
          <strong style={{ fontWeight: fontWeight.semibold }}>Visual analysis</strong>
          <span style={{ color: c.textSecondary }}>
            {' '}captures stills where the transcript suggests something is being shown, describes them, and lets
            the report say what was on screen and when. It adds roughly $0.20 per video and downloads each video
            once; frames are kept and reused by later runs.
          </span>
        </span>
      </label>
      {reason && (
        <div style={{ color: c.textSecondary, paddingLeft: space['6'] }}>
          {reason}
          {checked && (
            <>
              {' '}This run was set up with it on, so it will run without frames.{' '}
              <Button size="sm" variant="tertiary" type="button" onClick={() => onChange(false)}>
                Turn off
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
