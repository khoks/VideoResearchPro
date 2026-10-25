import { Button, Spinner } from '../primitives';
import { useObjectUrl } from '../../hooks/useObjectUrl';
import { useReportDocument } from '../../hooks/useReport';
import { useColors, useShadows } from '../../hooks/useTheme';
import { openBlobInNewTab } from '../../services/apiFiles';
import { fonts, fontSize, fontWeight, radius, space, z } from '../../theme';
import { REPORT_FRAME_SANDBOX } from '../../utils/reportDocument';

/**
 * The job page's quick peek at the stored HTML report (the reading room at
 * `/reports/:jobId` is the full view, S-8.8.1).
 *
 * T-8.8.1.5: the report is fetched with the bearer header and framed as a
 * blob: URL, sandboxed with nothing allowed to run. Until then the iframe's
 * `src` (and "Open in new tab") carried the JWT as `?token=`, which put it in
 * browser history, server logs and Referer headers.
 */
export function ReportPeekModal({ jobId, onClose }: { jobId: string; onClose: () => void }) {
  const c = useColors();
  const s = useShadows();
  const report = useReportDocument(jobId);
  const src = useObjectUrl(report.data);

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(20, 17, 14, 0.55)',
        zIndex: z.modal,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          width: '92vw',
          height: '92vh',
          background: c.surface,
          borderRadius: radius.lg,
          border: `1px solid ${c.border}`,
          boxShadow: s.floating,
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: `${space['3']} ${space['4']}`,
            borderBottom: `1px solid ${c.border}`,
            gap: space['3'],
            background: c.surfaceAlt,
          }}
        >
          <h3
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.md,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            Research report
          </h3>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'] }}>
            <Button
              size="sm"
              variant="secondary"
              disabled={!report.data}
              // Its own short-lived URL: the frame's is revoked when the modal closes.
              onClick={() => report.data && openBlobInNewTab(report.data)}
            >
              Open in new tab
            </Button>
            <Button size="sm" variant="tertiary" onClick={onClose}>
              Close
            </Button>
          </div>
        </div>
        {src ? (
          <iframe
            src={src}
            sandbox={REPORT_FRAME_SANDBOX}
            referrerPolicy="no-referrer"
            style={{ width: '100%', flex: 1, border: 'none' }}
            title="Research Report"
          />
        ) : (
          <div
            role={report.isError ? 'alert' : 'status'}
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: space['2'],
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
            }}
          >
            {report.isError ? (
              report.error?.response?.status === 404 ? 'This run has no report.' : 'Could not load the report.'
            ) : (
              <>
                <Spinner size={16} /> Loading the report…
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
