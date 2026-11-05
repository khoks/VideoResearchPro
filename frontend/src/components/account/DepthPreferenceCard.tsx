/**
 * T-1.15.3.9: the depth this person's pages start from. Auto, the default,
 * changes nothing and sends nothing. Saved at once, like the rest of this page.
 *
 * The server never applies it. The submit form, the knowledge drawer and the Q&A
 * panels preset their own control from it, so what a request carries is always
 * what the page showed.
 */
import { Card } from '../primitives';
import { DepthSelect } from '../common/DepthSelect';
import { useMe, usePreferredDepth, useSetPreferredDepth } from '../../hooks/useMe';
import { useColors } from '../../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';

export function DepthPreferenceCard() {
  const c = useColors();
  const me = useMe();
  const preferred = usePreferredDepth();
  const save = useSetPreferredDepth();
  return (
    <Card data-depth-preference="">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: space['4'],
          flexWrap: 'wrap',
        }}
      >
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <h2
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            Default depth
          </h2>
          <p
            style={{
              margin: `${space['1']} 0 0`,
              fontFamily: fonts.body,
              fontSize: fontSize.sm,
              color: c.textSecondary,
              lineHeight: lineHeight.normal,
              maxWidth: '75ch',
            }}
          >
            Where new topic runs, knowledge reports and questions start. Auto sizes each one to its material. A depth you
            pick on a page wins over this one, and so does the depth a run was given, on that run&apos;s page.
          </p>
        </div>
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: space['2'],
            fontFamily: fonts.ui,
            fontSize: fontSize.sm,
            color: c.textSecondary,
          }}
        >
          Default depth
          <DepthSelect
            value={preferred}
            onChange={(depth) => save.mutate(depth)}
            unsetLabel="Auto"
            aria-label="Default depth"
            title="Auto sizes each run, report and answer to its material."
            disabled={!me.data || save.isPending}
          />
        </label>
      </div>
    </Card>
  );
}
