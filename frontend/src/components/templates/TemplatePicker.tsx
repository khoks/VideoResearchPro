import { Link } from 'react-router-dom';
import type { JobTemplate } from '../../services/jobTemplatesApi';
import { Select } from '../primitives';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, space } from '../../theme';

/** "Start from a template" on the submit page: the reader's templates, then
 * the starters. Choosing one fills the form; the topic stays theirs. */
export function TemplatePicker({
  templates,
  onPick,
}: {
  templates: JobTemplate[];
  onPick: (template: JobTemplate) => void;
}) {
  const c = useColors();
  const own = templates.filter((t) => !t.builtin);
  const starters = templates.filter((t) => t.builtin);
  if (templates.length === 0) return null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: space['3'],
        flexWrap: 'wrap',
        marginBottom: space['4'],
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        color: c.textSecondary,
      }}
    >
      <span>Start from a template</span>
      <div style={{ flex: '1 1 240px' }}>
        <Select
          value=""
          onChange={(e) => {
            const t = templates.find((x) => x.id === e.target.value);
            if (t) onPick(t);
          }}
          aria-label="Start from a template"
        >
          <option value="">Choose a template…</option>
          {own.length > 0 && (
            <optgroup label="Your templates">
              {own.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {t.job_type} · v{t.version}
                  {t.problems.length > 0 ? ' (needs a change)' : ''}
                </option>
              ))}
            </optgroup>
          )}
          {starters.length > 0 && (
            <optgroup label="Starters">
              {starters.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name} · {t.job_type}
                </option>
              ))}
            </optgroup>
          )}
        </Select>
      </div>
      <Link to="/templates" style={{ color: c.accent, textDecoration: 'none', whiteSpace: 'nowrap' }}>
        Manage templates →
      </Link>
    </div>
  );
}
