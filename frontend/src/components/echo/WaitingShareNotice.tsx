import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useColors } from '../../hooks/useTheme';
import { hasPendingShares, SHARE_REVIEW_PATH } from '../../services/shareTarget';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../../theme';

/**
 * A share waiting on this device, seen from a page other than `/` (T-3.7.6.3).
 *
 * The gate at `/` is the one redirect a waiting share gets (D-137), so a deep
 * link passes it by, and the share would sit until the next visit to `/`. This
 * is a link and nothing more: the reader stays on the page they came for, and
 * the one tap that posts a share stays on the review page. It looks again on each
 * move, because the review page ends the wait, and it shows nothing where
 * the gate or the review page already has the share in hand.
 */
export function WaitingShareNotice() {
  const c = useColors();
  const { pathname } = useLocation();
  const elsewhere = pathname !== '/' && pathname !== SHARE_REVIEW_PATH;
  const [waiting, setWaiting] = useState(false);

  // What it knew ends where the share is in hand, or the way back would announce
  // the one the reader just dealt with until the next look answers.
  if (!elsewhere && waiting) setWaiting(false);

  useEffect(() => {
    if (!elsewhere) return;
    let live = true;
    void hasPendingShares().then((found) => {
      if (live) setWaiting(found);
    });
    return () => {
      live = false;
    };
  }, [elsewhere, pathname]);

  if (!elsewhere || !waiting) return null;
  return (
    <div
      role="status"
      style={{
        background: c.accentSubtle,
        border: `1px solid ${c.accent}`,
        color: c.textPrimary,
        padding: `${space['3']} ${space['4']}`,
        margin: `${space['4']} ${space['6']} 0`,
        borderRadius: radius.md,
        display: 'flex',
        alignItems: 'center',
        flexWrap: 'wrap',
        gap: `${space['1']} ${space['3']}`,
        fontFamily: fonts.ui,
        fontSize: fontSize.sm,
        lineHeight: lineHeight.snug,
      }}
    >
      <span style={{ flex: '1 1 240px' }}>A share is waiting on this device. Nothing is added until you say so.</span>
      <Link to={SHARE_REVIEW_PATH} className="waiting-share-link" style={{ color: c.accent, fontWeight: fontWeight.semibold }}>
        Review it
      </Link>
    </div>
  );
}
