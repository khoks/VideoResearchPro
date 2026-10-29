import { featureFlags } from '../config/features';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  useDeleteTemplate,
  useJobTemplates,
  useTemplateVersions,
  useUpdateTemplate,
} from '../hooks/useJobTemplates';
import { SaveTemplateModal } from '../components/templates';
import { Badge, Button, Card, EmptyState, Skeleton, Spinner } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import { fonts, fontSize, fontWeight, lineHeight, measure, space } from '../theme';
import { formatDate } from '../utils/formatters';
import { apiErrorMessage } from '../utils/apiError';
import { isDefaultSourceTypes, sourceTypeLabel } from '../utils/jobForm';
import type { JobTemplate, TemplateParameters } from '../services/jobTemplatesApi';

/**
 * `/templates` (S-8.6.1): the reader's job templates and the starters.
 * "Use" opens the submit form filled from the template; a template's own
 * history is a list of immutable versions, newest first.
 */
export function TemplatesPage() {
  const c = useColors();
  const navigate = useNavigate();
  const templatesQuery = useJobTemplates();
  const [renaming, setRenaming] = useState<JobTemplate | null>(null);
  const update = useUpdateTemplate();

  const templates = templatesQuery.data ?? [];
  const own = templates.filter((t) => !t.builtin);
  const starters = templates.filter((t) => t.builtin);
  const use = (t: JobTemplate) => navigate('/submit', { state: { fromTemplateId: t.id } });

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['5'] }}>
        <h1
          style={{
            fontFamily: fonts.display,
            fontSize: fontSize['2xl'],
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            margin: 0,
            lineHeight: lineHeight.tight,
          }}
        >
          Templates
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontStyle: 'italic',
            fontSize: fontSize.sm,
            color: c.textMuted,
            margin: `${space['2']} 0 0`,
            maxWidth: measure.reading,
          }}
        >
          A good run is a recipe. Keep the recipe; change only the topic.
        </p>
      </header>

      {templatesQuery.isLoading ? (
        <div aria-busy style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>
          <Skeleton variant="row" height={88} />
          <Skeleton variant="row" height={88} />
        </div>
      ) : templatesQuery.isError ? (
        <EmptyState
          title="Couldn't load your templates."
          description="Something blocked the fetch."
          action={
            <Button variant="secondary" onClick={() => void templatesQuery.refetch()}>
              Retry
            </Button>
          }
        />
      ) : (
        <>
          <Section title="Your templates">
            {own.length === 0 ? (
              <EmptyState
                size="sm"
                title="No templates of your own yet."
                description={
                  <>
                    Use “Save as template” on a finished run, or on the{' '}
                    <Link to="/submit" style={{ color: c.accent }}>
                      submit form
                    </Link>
                    .
                  </>
                }
              />
            ) : (
              own.map((t) => (
                <TemplateCard key={t.id} template={t} onUse={() => use(t)} onRename={() => setRenaming(t)} />
              ))
            )}
          </Section>
          {starters.length > 0 && (
            <Section title="Starters">
              {starters.map((t) => (
                <TemplateCard key={t.id} template={t} onUse={() => use(t)} />
              ))}
            </Section>
          )}
        </>
      )}

      <SaveTemplateModal
        open={!!renaming}
        onClose={() => setRenaming(null)}
        title="Rename template"
        submitLabel="Save"
        initialName={renaming?.name ?? ''}
        initialDescription={renaming?.description ?? null}
        onSubmit={(v) => update.mutateAsync({ id: renaming!.id, body: v })}
      />
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const c = useColors();
  return (
    <section style={{ marginBottom: space['6'] }}>
      <h2
        style={{
          fontFamily: fonts.display,
          fontSize: fontSize.lg,
          fontWeight: fontWeight.semibold,
          color: c.textPrimary,
          margin: `0 0 ${space['3']}`,
        }}
      >
        {title}
      </h2>
      <div style={{ display: 'flex', flexDirection: 'column', gap: space['3'] }}>{children}</div>
    </section>
  );
}

export function summariseParameters(p: TemplateParameters): string {
  const parts: string[] = [];
  if (p.job_type === 'topic') parts.push(`${p.num_videos} videos`);
  if (p.job_type === 'topic' && p.source_types?.length && !isDefaultSourceTypes(p.source_types)) {
    parts.push(p.source_types.map(sourceTypeLabel).join(' + '));
  }
  if (p.channel_list?.length) parts.push(`${p.channel_list.length} channel${p.channel_list.length === 1 ? '' : 's'}`);
  else if (p.job_type !== 'topic') parts.push('you add the channels');
  if (p.job_type === 'channel' && p.videos_per_channel) parts.push(`${p.videos_per_channel} per channel`);
  if (p.output_length && p.output_length !== 'auto') parts.push(`${p.output_length} report`);
  if (p.preferred_channels?.length) parts.push(`${p.preferred_channels.length} preferred channel${p.preferred_channels.length === 1 ? '' : 's'}`);
  if (p.min_duration_minutes || p.max_duration_minutes) {
    parts.push(`${p.min_duration_minutes ?? 0}–${p.max_duration_minutes ?? '∞'} min`);
  }
  if (p.channel_type_filters?.length) parts.push(p.channel_type_filters.join(', '));
  if (p.visual_analysis) parts.push(featureFlags.visualAnalysis ? 'visual analysis' : 'visual analysis (paused)');
  return parts.join(' · ');
}

function TemplateCard({
  template,
  onUse,
  onRename,
}: {
  template: JobTemplate;
  onUse: () => void;
  onRename?: () => void;
}) {
  const c = useColors();
  const del = useDeleteTemplate();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const p = template.parameters;

  return (
    <Card>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: space['4'], flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: space['2'], flexWrap: 'wrap' }}>
            <span
              style={{
                fontFamily: fonts.display,
                fontSize: fontSize.md,
                fontWeight: fontWeight.semibold,
                color: c.textPrimary,
              }}
            >
              {template.name}
            </span>
            <Badge size="sm">{template.job_type}</Badge>
            {template.builtin ? (
              <Badge size="sm" tone="accent">
                starter
              </Badge>
            ) : (
              <span style={{ fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
                v{template.version} · updated {formatDate(template.updated_at)}
              </span>
            )}
          </div>
          {template.description && (
            <p style={{ margin: `${space['1']} 0 0`, fontFamily: fonts.body, fontSize: fontSize.sm, color: c.textSecondary }}>
              {template.description}
            </p>
          )}
          <p style={{ margin: `${space['1']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textMuted }}>
            {summariseParameters(p)}
          </p>
          {p.search_instructions && (
            <p
              style={{
                margin: `${space['1']} 0 0`,
                fontFamily: fonts.body,
                fontSize: fontSize.sm,
                fontStyle: 'italic',
                color: c.textSecondary,
              }}
            >
              “{p.search_instructions}”
            </p>
          )}
          {template.problems.length > 0 && (
            <p role="alert" style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.warn }}>
              {template.problems.join(' ')}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: space['2'], flexShrink: 0, flexWrap: 'wrap' }}>
          <Button size="sm" onClick={onUse}>
            Use
          </Button>
          {!template.builtin && (
            <>
              {template.version > 1 && (
                <Button size="sm" variant="tertiary" onClick={() => setShowHistory((s) => !s)} aria-expanded={showHistory}>
                  History
                </Button>
              )}
              {onRename && (
                <Button size="sm" variant="tertiary" onClick={onRename}>
                  Rename
                </Button>
              )}
              {confirmDelete ? (
                <>
                  <Button
                    size="sm"
                    variant="danger"
                    loading={del.isPending}
                    onClick={() =>
                      del.mutate(template.id, {
                        onError: (err) => setError(apiErrorMessage(err, 'Could not delete the template.')),
                      })
                    }
                  >
                    Delete
                  </Button>
                  <Button size="sm" variant="tertiary" onClick={() => setConfirmDelete(false)}>
                    Keep
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="tertiary" onClick={() => setConfirmDelete(true)}>
                  Delete…
                </Button>
              )}
            </>
          )}
        </div>
      </div>
      {confirmDelete && (
        <p style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.textSecondary }}>
          Runs that started from it keep pointing at the version they used.
        </p>
      )}
      {showHistory && <History templateId={template.id} />}
      {error && (
        <p role="alert" style={{ margin: `${space['2']} 0 0`, fontFamily: fonts.ui, fontSize: fontSize.sm, color: c.error }}>
          {error}
        </p>
      )}
    </Card>
  );
}

function History({ templateId }: { templateId: string }) {
  const c = useColors();
  const { data, isLoading } = useTemplateVersions(templateId);
  if (isLoading) return <Spinner size={14} />;
  return (
    <ol style={{ margin: `${space['3']} 0 0`, paddingLeft: space['5'], fontFamily: fonts.ui, fontSize: fontSize.xs, color: c.textSecondary }}>
      {(data ?? []).map((v) => (
        <li key={v.version} style={{ marginBottom: space['1'] }}>
          <strong style={{ color: c.textPrimary }}>v{v.version}</strong> · {formatDate(v.created_at)} ·{' '}
          {summariseParameters(v.parameters)}
        </li>
      ))}
    </ol>
  );
}
