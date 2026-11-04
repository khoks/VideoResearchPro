/**
 * The compact depth control (R4 / D-064) for one ask or one knowledge report:
 * "no preference" plus the three explicit depths. Additive and ignorable, like
 * the submit form's "Report depth": leaving it on the first option sends
 * nothing, so the server's default stands.
 *
 * Only the select itself; each surface wraps it in the label style it already
 * uses for its other per-ask option (the answer language).
 */
import { Select } from '../primitives';
import { DEPTHS, depthLabel, depthOf, type Depth } from '../../utils/depth';

interface Props {
  value: Depth | null;
  onChange: (depth: Depth | null) => void;
  /** What the first option, "no preference", is called here: "Default", "Auto". */
  unsetLabel: string;
  id?: string;
  'aria-label'?: string;
  title?: string;
  disabled?: boolean;
}

export function DepthSelect({ value, onChange, unsetLabel, id, title, disabled, ...rest }: Props) {
  return (
    <Select
      id={id}
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
