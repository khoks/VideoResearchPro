import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import api from '../services/api';
import { useColors } from '../hooks/useTheme';
import { useJobStore } from '../stores/jobStore';
import { fonts, fontSize, fontWeight, lineHeight, radius, space } from '../theme';

interface PersonalContext {
  id: string;
  kind: string;
  key: string;
  value: string;
  source: string;
  captured_at: string;
}

interface EchoStatus {
  ready: boolean;
  total_rows: number;
  distinct_sources: number;
  has_personality_trait: boolean;
  threshold_total: number;
  threshold_sources: number;
}

const SUPPORTED_KINDS = [
  'location',
  'interest',
  'hobby',
  'work',
  'talent',
  'skill',
  'personality_trait',
  'life_event',
  'daily_routine',
  'place',
];

/**
 * Echo page — Studio-tier-only personal-context manager.
 *
 * Backend foundation shipped per I-3 (PR #172): CRUD on PersonalContext
 * rows + cold-start readiness threshold (E-3.5). Concrete pull-mode
 * connectors (YouTube watch / Spotify / email) and the "speak as me"
 * agent are E-3.2 / E-3.4 follow-ups, not yet shipped.
 *
 * This page exercises the shipped foundation: add a fact, list facts,
 * see the readiness meter.
 */
export function EchoPage() {
  const c = useColors();
  const qc = useQueryClient();
  const pushToast = useJobStore((s) => s.pushToast);
  const [kind, setKind] = useState('interest');
  const [key, setKey] = useState('');
  const [value, setValue] = useState('');

  const status = useQuery<EchoStatus>({
    queryKey: ['echo', 'status'],
    queryFn: async () => (await api.get('/echo/status')).data,
  });
  const list = useQuery<PersonalContext[]>({
    queryKey: ['echo', 'context'],
    queryFn: async () => (await api.get('/echo/context')).data,
  });

  const create = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/echo/context', {
        kind,
        key,
        value,
        source: 'manual',
      });
      return data;
    },
    onSuccess: () => {
      setKey('');
      setValue('');
      qc.invalidateQueries({ queryKey: ['echo', 'context'] });
      qc.invalidateQueries({ queryKey: ['echo', 'status'] });
      pushToast('success', 'Context added.');
    },
  });

  return (
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <header style={{ marginBottom: space['6'] }}>
        <h1
          style={{
            margin: 0,
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
          }}
        >
          Echo
        </h1>
        <p
          style={{
            margin: `${space['2']} 0 0`,
            fontFamily: fonts.body,
            fontSize: fontSize.md,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
          }}
        >
          Your personal-context store. Echo learns about you so it can eventually echo your voice —
          identity, interests, hobbies, work, talents, skills, places, life events. The "speak as me"
          agent (E-3.4) will draw from this once enough context has accumulated.
        </p>
      </header>

      {/* Readiness card */}
      <div
        style={{
          background: c.surface,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          padding: space['5'],
          marginBottom: space['6'],
        }}
      >
        <h2 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.textPrimary }}>
          Cold-start readiness
        </h2>
        {status.data ? (
          <div style={{ marginTop: space['3'], fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
            <p style={{ margin: 0 }}>
              <strong style={{ color: c.textPrimary }}>{status.data.total_rows}</strong> of {status.data.threshold_total} context rows ·{' '}
              <strong style={{ color: c.textPrimary }}>{status.data.distinct_sources}</strong> of {status.data.threshold_sources} distinct sources
            </p>
            <p style={{ margin: `${space['2']} 0 0` }}>
              Personality trait recorded: <strong>{status.data.has_personality_trait ? 'yes' : 'no'}</strong>
            </p>
            <p style={{ margin: `${space['3']} 0 0`, fontStyle: 'italic', color: status.data.ready ? c.forest : c.warn }}>
              {status.data.ready
                ? 'Echo is ready to speak as you. (Speak-as-me agent — E-3.4 — coming soon.)'
                : 'Echo is still learning. Add more context above to unlock the "speak as me" agent when it ships.'}
            </p>
          </div>
        ) : (
          <p style={{ marginTop: space['3'], color: c.textMuted, fontStyle: 'italic' }}>Loading readiness…</p>
        )}
      </div>

      {/* Add-fact form */}
      <div
        style={{
          background: c.surface,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
          padding: space['5'],
          marginBottom: space['6'],
        }}
      >
        <h2 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.textPrimary }}>
          Add a fact about yourself
        </h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (!key.trim() || !value.trim()) return;
            create.mutate();
          }}
          style={{ marginTop: space['3'], display: 'flex', flexDirection: 'column', gap: space['3'] }}
        >
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 2fr', gap: space['3'] }}>
            <Labeled label="Kind">
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value)}
                style={inputStyle(c)}
              >
                {SUPPORTED_KINDS.map((k) => (
                  <option key={k} value={k}>
                    {k}
                  </option>
                ))}
              </select>
            </Labeled>
            <Labeled label="Key (short label)">
              <input
                type="text"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="e.g. 'Indian macroeconomics'"
                style={inputStyle(c)}
              />
            </Labeled>
          </div>
          <Labeled label="Value (the fact itself, in your own words)">
            <textarea
              value={value}
              onChange={(e) => setValue(e.target.value)}
              rows={3}
              placeholder="e.g. 'I follow Indian macroeconomic policy debates closely; especially RBI rate decisions and fiscal responses.'"
              style={{ ...inputStyle(c), resize: 'vertical', fontFamily: fonts.body }}
            />
          </Labeled>
          <div>
            <button
              type="submit"
              disabled={create.isPending || !key.trim() || !value.trim()}
              style={{
                padding: `${space['2']} ${space['5']}`,
                background: c.accent,
                color: c.bg,
                border: 'none',
                borderRadius: radius.md,
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                fontWeight: fontWeight.semibold,
                cursor: create.isPending ? 'wait' : 'pointer',
                opacity: !key.trim() || !value.trim() ? 0.5 : 1,
              }}
            >
              {create.isPending ? 'Adding…' : 'Add context'}
            </button>
          </div>
        </form>
      </div>

      {/* Recorded facts */}
      <h2 style={{ margin: `0 0 ${space['3']}`, fontFamily: fonts.display, fontSize: fontSize.lg, color: c.textPrimary }}>
        Your context ({list.data?.length ?? 0})
      </h2>
      {list.isLoading && <p style={{ color: c.textMuted }}>Loading…</p>}
      {!list.isLoading && (!list.data || list.data.length === 0) && (
        <p style={{ fontFamily: fonts.body, fontStyle: 'italic', color: c.textMuted }}>
          No context yet. Add your first fact above.
        </p>
      )}
      {list.data && list.data.length > 0 && (
        <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: space['2'] }}>
          {list.data.map((row) => (
            <li
              key={row.id}
              style={{
                background: c.surface,
                border: `1px solid ${c.border}`,
                borderRadius: radius.md,
                padding: `${space['3']} ${space['4']}`,
                display: 'flex',
                gap: space['3'],
                alignItems: 'baseline',
              }}
            >
              <span
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.xs,
                  fontWeight: fontWeight.semibold,
                  letterSpacing: '0.06em',
                  textTransform: 'uppercase',
                  color: c.accent,
                  background: c.accentSubtle,
                  padding: `2px ${space['2']}`,
                  borderRadius: radius.sm,
                  whiteSpace: 'nowrap',
                }}
              >
                {row.kind}
              </span>
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.sm, fontWeight: fontWeight.semibold, color: c.textPrimary }}>
                {row.key}:
              </span>
              <span style={{ fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary, flex: 1 }}>
                {row.value}
              </span>
            </li>
          ))}
        </ul>
      )}

      {/* Coming-soon footer */}
      <div
        style={{
          marginTop: space['8'],
          padding: space['5'],
          background: c.surfaceAlt,
          border: `1px solid ${c.border}`,
          borderRadius: radius.lg,
        }}
      >
        <h3 style={{ margin: 0, fontFamily: fonts.display, fontSize: fontSize.md, color: c.textPrimary }}>
          Coming soon
        </h3>
        <ul
          style={{
            margin: `${space['2']} 0 0`,
            paddingLeft: space['5'],
            fontFamily: fonts.body,
            fontSize: fontSize.sm,
            color: c.textSecondary,
            lineHeight: lineHeight.normal,
          }}
        >
          <li>Pull-mode connectors: YouTube watch history, Spotify, email, calendar (E-3.2)</li>
          <li>Voice & style capture from your writing (E-3.3)</li>
          <li>"Speak as me" agent — drafts responses in your voice (E-3.4)</li>
          <li>Always-evokable Echo bubble on every page (cmd+E / ctrl+E)</li>
        </ul>
      </div>
    </div>
  );
}

function Labeled({ label, children }: { label: string; children: React.ReactNode }) {
  const c = useColors();
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: space['1'] }}>
      <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary, fontWeight: fontWeight.medium }}>
        {label}
      </span>
      {children}
    </label>
  );
}

function inputStyle(c: ReturnType<typeof useColors>): React.CSSProperties {
  return {
    fontFamily: fonts.ui,
    fontSize: fontSize.sm,
    padding: `${space['2']} ${space['3']}`,
    background: c.bg,
    color: c.textPrimary,
    border: `1px solid ${c.border}`,
    borderRadius: radius.sm,
    outline: 'none',
    width: '100%',
  };
}
