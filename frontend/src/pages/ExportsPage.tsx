import { useAuth } from '../contexts/AuthContext';
import { useJobStore } from '../stores/jobStore';
import { exportsApi } from '../services/exportsApi';
import { downloadUrl } from '../utils/download';
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
  url: string;
  filename: string;
  variant: 'primary' | 'secondary';
}

interface DatasetCard {
  title: string;
  description: string;
  downloads: Download[];
}

export function ExportsPage() {
  const c = useColors();
  const { token } = useAuth();
  const pushToast = useJobStore((s) => s.pushToast);

  const cards: DatasetCard[] = [
    {
      title: 'Q&A dataset',
      description:
        'Every question you asked together with the assistant answer, packaged for fine-tuning.',
      downloads: [
        { label: 'OpenAI JSONL', url: exportsApi.getQaOpenaiUrl(token), filename: 'qa-dataset-openai.jsonl', variant: 'primary' },
        { label: 'Tuple JSONL', url: exportsApi.getQaTupleUrl(token), filename: 'qa-dataset-tuple.jsonl', variant: 'secondary' },
      ],
    },
    {
      title: 'Knowledge dataset',
      description:
        'Transcript chunks and report excerpts from your library, ready to feed into a model.',
      downloads: [
        { label: 'OpenAI JSONL', url: exportsApi.getKnowledgeOpenaiUrl(token), filename: 'knowledge-dataset-openai.jsonl', variant: 'primary' },
        { label: 'Tuple JSONL', url: exportsApi.getKnowledgeTupleUrl(token), filename: 'knowledge-dataset-tuple.jsonl', variant: 'secondary' },
      ],
    },
    {
      title: 'Your notes',
      description:
        'Every note you have written, withdrawn ones included. Markdown to read; JSON-LD (W3C Web Annotation) to keep every field exactly, and to take with you.',
      downloads: [
        { label: 'Markdown', url: exportsApi.getNotesMarkdownUrl(token), filename: 'notes.md', variant: 'primary' },
        { label: 'JSON-LD', url: exportsApi.getNotesJsonldUrl(token), filename: 'notes.jsonl', variant: 'secondary' },
      ],
    },
  ];

  const handleDownload = (url: string, filename: string) => {
    if (!token) {
      pushToast('error', 'You must be signed in to download exports.');
      return;
    }
    downloadUrl(url, filename);
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
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: space['2'] }}>
              {card.downloads.map((d) => (
                <Button key={d.label} variant={d.variant} onClick={() => handleDownload(d.url, d.filename)}>
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
