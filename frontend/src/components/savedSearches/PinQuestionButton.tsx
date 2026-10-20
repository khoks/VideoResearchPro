import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { useTierCapabilities } from '../../hooks/useTierCapabilities';
import { useCreateSavedSearch } from '../../hooks/useSavedSearches';
import { Button, Modal } from '../primitives';
import { ScheduleFields } from './ScheduleFields';
import { apiErrorMessage } from '../../utils/apiError';
import { defaultCadence, describeCadence } from '../../utils/cadence';
import type { Cadence } from '../../services/savedSearchesApi';
import { fonts, fontSize, lineHeight, space } from '../../theme';

/**
 * "Pin this question" (S-8.3.2): re-ask a library question on a schedule.
 * Shown only on tiers with the `saved_searches` feature. The dialog asks
 * only for when; the question and its language come from the exchange.
 */
export function PinQuestionButton({
  question,
  answerLanguage,
  scope = null,
}: {
  question: string;
  answerLanguage: string;
  /** S-8.1.4: a shelf answer pins the shelf; null pins the whole library. */
  scope?: { shelf_id: string } | null;
}) {
  const c = useColors();
  const { has } = useTierCapabilities();
  const create = useCreateSavedSearch();
  const [open, setOpen] = useState(false);
  const [cadence, setCadence] = useState<Cadence>(defaultCadence);
  const [notifyEmail, setNotifyEmail] = useState(true);
  const [done, setDone] = useState(false);

  if (!has('saved_searches')) return null;

  const close = () => {
    setOpen(false);
    create.reset();
  };

  const save = async () => {
    try {
      await create.mutateAsync({ question, cadence, answer_language: answerLanguage, scope, notify_email: notifyEmail });
      setDone(true);
      setOpen(false);
    } catch {
      /* the error renders in the dialog */
    }
  };

  if (done) {
    return (
      <Link to="/saved-searches" style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.accent, alignSelf: 'center' }}>
        Pinned
      </Link>
    );
  }

  return (
    <>
      <Button size="sm" variant="tertiary" onClick={() => setOpen(true)}>
        Pin this question
      </Button>
      <Modal
        open={open}
        onClose={close}
        title="Pin this question"
        footer={
          <>
            <Button variant="tertiary" onClick={close}>
              Cancel
            </Button>
            <Button onClick={() => void save()} loading={create.isPending}>
              Pin it
            </Button>
          </>
        }
      >
        <p style={{ fontFamily: fonts.body, fontSize: fontSize.base, color: c.textSecondary, lineHeight: lineHeight.normal, margin: `0 0 ${space['4']}` }}>
          Pratidhvani re-asks it across your library on a schedule, so you see when the answer moves. Each run counts as one
          library question this month.
        </p>
        <blockquote style={{ margin: `0 0 ${space['4']}`, fontFamily: fonts.display, fontSize: fontSize.md, color: c.textPrimary }}>
          {question}
        </blockquote>
        <ScheduleFields value={cadence} onChange={setCadence} />
        <label style={{ display: 'flex', alignItems: 'center', gap: space['2'], marginTop: space['3'], minHeight: 44, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textPrimary }}>
          <input type="checkbox" checked={notifyEmail} onChange={(e) => setNotifyEmail(e.target.checked)} style={{ width: 18, height: 18, accentColor: c.accent }} />
          Email me when the answer changes
        </label>
        <p style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, margin: `${space['2']} 0 0` }}>{describeCadence(cadence)}</p>
        {create.isError && (
          <p role="alert" style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error, margin: `${space['3']} 0 0` }}>
            {apiErrorMessage(create.error, 'The question could not be pinned. Try again.')}
          </p>
        )}
      </Modal>
    </>
  );
}
