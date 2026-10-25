import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useOnboarding } from '../hooks/useOnboarding';
import { useJobStore } from '../stores/jobStore';
import { exportsApi, type ExportFile } from '../services/exportsApi';
import { Button, Card } from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  measure,
  space,
} from '../theme';

interface Download {
  label: string;
  file: ExportFile;
  variant: 'primary' | 'secondary';
}

interface DatasetCard {
  title: string;
  description: string;
  downloads: Download[];
  /** Shown when the dataset would download empty (S-8.10.2). */
  emptyNote?: string;
}

export function ExportsPage() {
  const c = useColors();
  const { token } = useAuth();
  const pushToast = useJobStore((s) => s.pushToast);
  // The onboarding milestones already count questions on every surface.
  const questions = useOnboarding().data?.milestones.questions;

  const cards: DatasetCard[] = [
    {
      title: 'Q&A dataset',
      description:
        'Every question you asked together with the assistant answer, packaged for fine-tuning.',
      emptyNote:
        questions === 0
          ? 'You have not asked a question yet, so both files download empty. Ask a run or the library first.'
          : undefined,
      downloads: [
        { label: 'OpenAI JSONL', file: 'qaOpenai', variant: 'primary' },
        { label: 'Tuple JSONL', file: 'qaTuple', variant: 'secondary' },
      ],
    },
    {
      title: 'Knowledge dataset',
      description:
        'Transcript chunks and report excerpts from your library, ready to feed into a model.',
      downloads: [
        { label: 'OpenAI JSONL', file: 'knowledgeOpenai', variant: 'primary' },
        { label: 'Tuple JSONL', file: 'knowledgeTuple', variant: 'secondary' },
      ],
    },
    {
      title: 'Your notes',
      description:
        'Every note you have written, withdrawn ones included. Markdown to read; JSON-LD (W3C Web Annotation) to keep every field exactly, and to take with you.',
      downloads: [
        { label: 'Markdown', file: 'notesMarkdown', variant: 'primary' },
        { label: 'JSON-LD', file: 'notesJsonld', variant: 'secondary' },
      ],
    },
  ];

  // T-8.8.1.5: fetched with the header and saved from a blob: URL, so the
  // JWT never rides in a link. The whole file is fetched before it is saved.
  const [busy, setBusy] = useState<ExportFile | null>(null);
  const handleDownload = async (file: ExportFile) => {
    if (!token) {
      pushToast('error', 'You must be signed in to download exports.');
      return;
    }
    setBusy(file);
    try {
      await exportsApi.download(file);
    } catch {
      pushToast('error', 'Could not fetch the export. Try again in a moment.');
    } finally {
      setBusy(null);
    }
  };

  return (
    <div style={{ maxWidth: measure.grid, margin: '0 auto' }}>
      <header style={{ marginBottom: space['6'] }}>
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
          Exports
        </h1>
        <p
          style={{
            fontFamily: fonts.body,
            fontSize: fontSize.base,
            color: c.textSecondary,
            margin: `${space['2']} 0 0`,
            lineHeight: lineHeight.normal,
            maxWidth: measure.reading,
          }}
        >
          Download your personal wiki as JSONL fine-tune datasets, each in the OpenAI chat format and a plain tuple format, and your own notes as Markdown or JSON-LD.
        </p>
      </header>

      <div style={{ display: 'grid', gap: space['4'] }}>
        {cards.map((card) => (
          <Card key={card.title}>
            <h2
              style={{
                margin: `0 0 ${space['2']}`,
                fontFamily: fonts.display,
                fontSize: fontSize.lg,
                fontWeight: fontWeight.semibold,
                color: c.textPrimary,
              }}
            >
              {card.title}
            </h2>
            <p
              style={{
                margin: `0 0 ${space['4']}`,
                fontFamily: fonts.body,
                fontSize: fontSize.base,
                color: c.textSecondary,
                lineHeight: lineHeight.normal,
                maxWidth: measure.reading,
              }}
            >
              {card.description}
            </p>
            {card.emptyNote && (
              <p
                role="note"
                style={{
                  margin: `0 0 ${space['4']}`,
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  color: c.textMuted,
                  maxWidth: measure.reading,
                }}
              >
                {card.emptyNote}
              </p>
            )}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'] }}>
              {card.downloads.map((d) => (
                <Button
                  key={d.label}
                  variant={d.variant}
                  loading={busy === d.file}
                  disabled={busy !== null && busy !== d.file}
                  onClick={() => handleDownload(d.file)}
                >
                  {d.label}
                </Button>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
