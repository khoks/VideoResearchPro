import { Link } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { useOnboarding, useUpdateOnboarding } from '../../hooks/useOnboarding';
import { Button, Card } from '../primitives';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

/**
 * First-run checklist on the jobs page (S-8.10.2, plan M10): three
 * milestones, each with the one action that completes it. Persistent and
 * dismissible (the state is on the server, so a dismissal holds on every
 * device), and it disappears by itself once all three are done — the
 * pattern comparable products use instead of a modal.
 */
export function ChecklistCard() {
  const c = useColors();
  const { data } = useOnboarding();
  const update = useUpdateOnboarding();
  if (!data) return null;
  const m = data.milestones;
  const first = m.first_job;
  const items = [
    {
      done: m.jobs > 0,
      label: 'Start a research run',
      action: { to: data.onboarded_at || data.state.dismissed ? '/submit' : '/welcome', label: 'Start one' },
    },
    {
      done: m.report_opened,
      label: 'Read a report',
      action: first?.has_report ? { to: `/reports/${first.id}`, label: 'Open the first one' } : { label: 'When a run finishes' },
    },
    {
      done: m.questions > 0,
      label: 'Ask your sources a question',
      action: first && first.status === 'completed' ? { to: `/jobs/${first.id}`, label: 'Ask on the first run' } : { to: '/library/qa', label: 'Ask the library' },
    },
  ];
  const doneCount = items.filter((i) => i.done).length;
  if (data.state.checklist_dismissed || doneCount === items.length) return null;

  return (
    <Card style={{ marginBottom: space['4'] }}>
      <section aria-labelledby="checklist-title">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: space['3'], flexWrap: 'wrap' }}>
          <h2 id="checklist-title" style={{ fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary, margin: 0 }}>
            Getting started
          </h2>
          <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textMuted }}>
            {doneCount} of {items.length} done
          </span>
        </div>
        <ul style={{ listStyle: 'none', margin: `${space['3']} 0 0`, padding: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {items.map((item) => (
            <li key={item.label} style={{ display: 'flex', alignItems: 'center', gap: space['3'], minHeight: 32, fontFamily: fonts.ui, fontSize: fontSize.sm, lineHeight: lineHeight.snug }}>
              <span
                aria-hidden="true"
                style={{
                  width: 20, height: 20, flexShrink: 0, borderRadius: radius.pill,
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                  border: `1px solid ${item.done ? c.success : c.border}`,
                  background: item.done ? c.successSubtle : 'transparent',
                  color: c.success, fontSize: fontSize.xs,
                }}
              >
                {item.done ? '✓' : ''}
              </span>
              <span style={{ flex: 1, color: item.done ? c.textMuted : c.textPrimary, textDecoration: item.done ? 'line-through' : 'none' }}>
                {item.label}
                <span className="reader-sr-only">{item.done ? ' (done)' : ' (not done yet)'}</span>
              </span>
              {!item.done &&
                (item.action.to ? (
                  <Link to={item.action.to} style={{ color: c.accent }}>
                    {item.action.label}
                  </Link>
                ) : (
                  <span style={{ color: c.textMuted }}>{item.action.label}</span>
                ))}
            </li>
          ))}
        </ul>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: space['3'] }}>
          <Button size="sm" variant="tertiary" onClick={() => update.mutate({ checklist_dismissed: true })} loading={update.isPending}>
            Hide this
          </Button>
        </div>
      </section>
    </Card>
  );
}
