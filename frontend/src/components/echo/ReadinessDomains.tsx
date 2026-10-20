/**
 * The five readiness domains (S-3.5.1), each with its progress and what is
 * missing in words. The words come from the server, which measures every
 * domain from its store; this only lays them out. A connector that cannot be
 * connected yet (not set up on this install, or waiting on Google sign-in
 * setup) reads "not connected" with the reason, never as a failure.
 */
import { Link } from 'react-router-dom';
import { Badge } from '../primitives';
import { ProgressBar } from '../common/ProgressBar';
import { useColors } from '../../hooks/useTheme';
import type { ReadinessDomain, ReadinessSource } from '../../services/echoApi';
import { fonts, fontSize, fontWeight, lineHeight, space } from '../../theme';

const STATUS: Record<string, { label: string; tone: 'success' | 'accent' | 'neutral' | 'info' }> = {
  met: { label: 'Done', tone: 'success' },
  in_progress: { label: 'On the way', tone: 'accent' },
  not_started: { label: 'Not started', tone: 'neutral' },
  not_connected: { label: 'Not connected', tone: 'info' },
};

const SOURCE_STATUS: Record<string, string> = {
  connected: 'connected',
  imported: 'imported',
  not_connected: 'not connected',
};

function Sources({ sources }: { sources: ReadinessSource[] }) {
  const c = useColors();
  if (sources.length === 0) return null;
  return (
    <ul
      aria-label="Activity sources"
      style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 2 }}
    >
      {sources.map((s) => (
        <li key={s.name} data-source={s.name} style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
          <span style={{ color: c.textPrimary }}>{s.label}</span> · {SOURCE_STATUS[s.status] ?? s.status}
          {s.events > 0 && ` · ${s.events.toLocaleString()} ${s.events === 1 ? 'event' : 'events'}`}
          {s.reason && <span style={{ color: c.textMuted }}> — {s.reason}</span>}
        </li>
      ))}
    </ul>
  );
}

function VoiceDetails({ domain }: { domain: ReadinessDomain }) {
  const c = useColors();
  const test = domain.details.voice_test;
  const stability = domain.details.stability;
  const line = { margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted, lineHeight: lineHeight.snug };
  return (
    <>
      {stability && stability.measured === false && stability.reason && <p style={line}>{stability.reason}</p>}
      {test && (
        <p style={line} data-voice-test="">
          {test.eligible
            ? 'You have enough notes to take the voice test that switches on "speak as me".'
            : `"Speak as me" needs a voice test you take yourself, after ${test.notes + test.notes_needed} notes (${test.notes_needed} to go).`}
        </p>
      )}
    </>
  );
}

export function ReadinessDomains({ domains }: { domains: ReadinessDomain[] }) {
  const c = useColors();
  return (
    <ul
      data-readiness-domains=""
      style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: space['4'] }}
    >
      {domains.map((d) => {
        const status = STATUS[d.status] ?? STATUS.in_progress;
        return (
          <li key={d.key} data-domain={d.key} style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: space['2'] }}>
              <span style={{ flex: 1, fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.medium, color: c.textPrimary }}>
                {d.label}
              </span>
              <Badge tone={status.tone} size="sm">
                {status.label}
              </Badge>
            </div>
            <ProgressBar value={d.progress * 100} tone={d.met ? 'success' : 'accent'} />
            <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary, lineHeight: lineHeight.snug }}>
              {d.summary}
            </p>
            {d.missing && (
              <p style={{ margin: 0, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textPrimary, lineHeight: lineHeight.snug }}>
                {d.missing}
                {d.key === 'shares' && (
                  <>
                    {' '}
                    <Link to="/echo/inbox" style={{ color: c.accent }}>
                      Open the inbox
                    </Link>
                  </>
                )}
              </p>
            )}
            {d.key === 'activity' && d.details.sources && <Sources sources={d.details.sources} />}
            {d.key === 'voice' && <VoiceDetails domain={d} />}
          </li>
        );
      })}
    </ul>
  );
}
