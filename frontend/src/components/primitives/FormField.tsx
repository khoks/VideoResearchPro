import { useId, type ReactNode, type CSSProperties } from 'react';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, space } from '../../theme';

export interface FormFieldProps {
  label: ReactNode;
  /** Receives the generated id — caller wires it to the control via e.g. `htmlFor`. */
  children: (controlId: string) => ReactNode;
  /** Optional helper text. Rendered in `textSecondary`. */
  helperText?: ReactNode;
  /** Error message. When present, `helperText` is hidden and `errorText` is shown in `error`. */
  errorText?: ReactNode;
  required?: boolean;
  /** Shows an `(optional)` marker instead of an asterisk. */
  optional?: boolean;
  style?: CSSProperties;
}

/**
 * Wraps a label + control + helper/error text with a stable id chain.
 *
 * ```tsx
 * <FormField label="Email" helperText="We never share this" required>
 *   {(id) => <Input id={id} type="email" value={email} onChange={...} />}
 * </FormField>
 * ```
 */
export function FormField({ label, children, helperText, errorText, required, optional, style }: FormFieldProps) {
  const c = useColors();
  const controlId = useId();
  const describedById = `${controlId}-desc`;

  const labelStyle: CSSProperties = {
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    fontWeight: fontWeight.medium,
    color: c.textSecondary,
    display: 'flex',
    alignItems: 'baseline',
    gap: space['2'],
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: space['1'], ...style }}>
      <label htmlFor={controlId} style={labelStyle}>
        <span>{label}</span>
        {required && <span style={{ color: c.error }} aria-hidden>*</span>}
        {optional && !required && (
          <span style={{ color: c.textMuted, fontSize: fontSize.xs, fontWeight: fontWeight.regular }}>
            (optional)
          </span>
        )}
      </label>
      {children(controlId)}
      {errorText && (
        <p
          id={describedById}
          role="alert"
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.error,
            margin: 0,
          }}
        >
          {errorText}
        </p>
      )}
      {!errorText && helperText && (
        <p
          id={describedById}
          style={{
            fontFamily: fonts.ui,
            fontSize: fontSize.xs,
            color: c.textMuted,
            margin: 0,
          }}
        >
          {helperText}
        </p>
      )}
    </div>
  );
}
