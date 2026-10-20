import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge, Button, Card, Spinner } from '../primitives';
import { ScheduleFields } from '../savedSearches/ScheduleFields';
import { useDeleteNewsletter, useNewsletter, useSaveNewsletter, useSendNewsletterNow } from '../../hooks/useAuthor';
import { useColors } from '../../hooks/useTheme';
import { useJobStore } from '../../stores/jobStore';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';
import type { Cadence } from '../../services/savedSearchesApi';
import { defaultCadence, describeCadence, parseUtc } from '../../utils/cadence';
import { NEWSLETTER_SECTIONS, defaultNewsletterSections, sendStatusLabel } from '../../utils/authorOutputs';
import { formatDate } from '../../utils/formatters';

/**
 * S-6.4.2: the reader's digest by email. One subscription: a schedule in
 * their own timezone, the sections an issue has, on or off. Issues land in
 * the outputs list as well as the inbox; a period with nothing new sends
 * nothing.
 */
export function NewsletterCard() {
  const c = useColors();
  const pushToast = useJobStore((s) => s.pushToast);
  const sub = useNewsletter();
  const save = useSaveNewsletter();
  const remove = useDeleteNewsletter();
  const sendNow = useSendNewsletterNow();

  const [cadence, setCadence] = useState<Cadence>(defaultCadence);
  const [sections, setSections] = useState<Record<string, boolean>>(defaultNewsletterSections);
  const [dirty, setDirty] = useState(false);

  const current = sub.data;
  useEffect(() => {
    if (current && !dirty) {
      setCadence(current.cadence);
      setSections(current.sections);
    }
  }, [current, dirty]);

  const persist = (enabled: boolean) =>
    save.mutate(
      { cadence, sections, enabled },
      {
        onSuccess: () => {
          setDirty(false);
          pushToast('success', enabled ? 'Your digest is on.' : 'Your digest is off.');
        },
        onError: () => pushToast('error', 'Could not save the digest settings.'),
      },
    );

  const text = { margin: 0, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary, lineHeight: lineHeight.normal } as const;

  return (
    <Card style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: space['3'], flexWrap: 'wrap' }}>
        <span style={{ fontFamily: fonts.display, fontSize: fontSize.lg, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
          Digest by email
        </span>
        {current && <Badge tone={current.enabled ? 'success' : 'neutral'}>{current.enabled ? 'On' : 'Off'}</Badge>}
      </div>
      {sub.isLoading ? (
        <Spinner />
      ) : (
        <>
          <p style={text}>
            {current?.enabled
              ? `${describeCadence(current.cadence)}. Next issue ${
                  current.next_issue_at ? formatDate(parseUtc(current.next_issue_at).toISOString()) : 'when the schedule runs'
                }. A period with nothing new sends nothing.`
              : 'A regular email of what is new in your library, made from the same lists as a newsletter here. Nothing new, nothing sent.'}
          </p>
          <ScheduleFields
            value={cadence}
            onChange={(next) => {
              setCadence(next);
              setDirty(true);
            }}
          />
          <div style={{ display: 'flex', gap: space['3'], flexWrap: 'wrap' }}>
            {NEWSLETTER_SECTIONS.map((s) => (
              <label key={s.key} style={{ display: 'inline-flex', alignItems: 'center', gap: space['2'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={Boolean(sections[s.key])}
                  onChange={(e) => {
                    setSections((prev) => ({ ...prev, [s.key]: e.target.checked }));
                    setDirty(true);
                  }}
                  style={{ accentColor: c.accent }}
                />
                {s.label}
              </label>
            ))}
          </div>
          <div style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}>
            {current?.enabled ? (
              <>
                <Button size="sm" onClick={() => persist(true)} disabled={!dirty} loading={save.isPending}>
                  Save changes
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  loading={sendNow.isPending}
                  onClick={() =>
                    sendNow.mutate(undefined, {
                      onSuccess: () => pushToast('info', 'Making an issue now; it appears in your outputs when it is ready.'),
                      onError: () => pushToast('error', 'Could not start an issue.'),
                    })
                  }
                >
                  Send one now
                </Button>
                <Button size="sm" variant="tertiary" onClick={() => persist(false)}>
                  Turn off
                </Button>
              </>
            ) : (
              <Button size="sm" onClick={() => persist(true)} loading={save.isPending} disabled={!Object.values(sections).some(Boolean)}>
                Turn on
              </Button>
            )}
            {current && (
              <Button
                size="sm"
                variant="tertiary"
                style={{ color: c.error }}
                onClick={() =>
                  remove.mutate(undefined, {
                    onSuccess: () => pushToast('info', 'Unsubscribed. Past issues stay in your outputs.'),
                  })
                }
              >
                Unsubscribe
              </Button>
            )}
          </div>
          {current && current.sends.length > 0 && (
            <ul style={{ margin: 0, paddingLeft: space['4'], display: 'flex', flexDirection: 'column', gap: space['1'] }}>
              {current.sends.slice(0, 5).map((s) => (
                <li key={`${s.period_key}-${s.created_at}`} style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                  {formatDate(parseUtc(s.created_at).toISOString())} · {sendStatusLabel(s.status)}
                  {s.output_id && s.status !== 'skipped' && (
                    <>
                      {' · '}
                      <Link to={`/author/outputs/${s.output_id}`} style={{ color: c.accent }}>
                        read it
                      </Link>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Card>
  );
}
