/**
 * The compact depth control (R4 / D-064) for one ask or one knowledge report:
 * "no preference" plus the three explicit depths. Additive and ignorable, like
 * the submit form's "Report depth": leaving it on the first option sends
 * nothing, so the server's default stands.
 *
 * Only the select itself; each surface wraps it in the label style it already
 * uses for its other per-ask option (the answer language).
 */
import { Button, Select } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, space } from '../../theme';
import { DEPTHS, depthLabel, depthOf, type Depth } from '../../utils/depth';

interface Props {
  value: Depth | null;
  onChange: (depth: Depth | null) => void;
  /** What the first option, "no preference", is called here: "Default", "Auto". */
  unsetLabel: string;
  'aria-label'?: string;
  title?: string;
  disabled?: boolean;
}

export function DepthSelect({ value, onChange, unsetLabel, title, disabled, ...rest }: Props) {
  return (
    <Select
      aria-label={rest['aria-label']}
      title={title}
      value={value ?? ''}
      disabled={disabled}
      onChange={(e) => onChange(depthOf(e.target.value))}
      style={{ width: 'auto', minWidth: 120 }}
    >
      <option value="">{unsetLabel}</option>
      {DEPTHS.map((d) => (
        <option key={d} value={d}>
          {depthLabel(d)}
        </option>
      ))}
    </Select>
  );
}

/**
 * The depth picked for the next ask, for inside `DockedComposer`. On a phone
 * the select sits above the thread (the docked row has no width to spare
 * beside Ask), so it scrolls away from the composer; this keeps a picked depth
 * in view at the point of asking, and lets the reader drop it from there.
 * Nothing on Default. Shown under 640 px only (`.qa-composer-depth`, index.css):
 * on wide screens the select is already right above the composer.
 */
export function ComposerDepthNote({ depth, onClear }: { depth: Depth | null; onClear: () => void }) {
  const c = useColors();
  if (!depth) return null;
  return (
    <div
      className="qa-composer-depth"
      style={{
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: space['2'],
        marginBottom: space['2'],
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textSecondary,
      }}
    >
      <span>Answer depth for this ask: {depthLabel(depth)}</span>
      <Button size="sm" variant="tertiary" onClick={onClear}>
        Clear
      </Button>
    </div>
  );
}
