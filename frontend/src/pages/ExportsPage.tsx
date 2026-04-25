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

interface DatasetCard {
  title: string;
  description: string;
  openaiUrl: string;
  openaiFilename: string;
  tupleUrl: string;
  tupleFilename: string;
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
      openaiUrl: exportsApi.getQaOpenaiUrl(token),
      openaiFilename: 'qa-dataset-openai.jsonl',
      tupleUrl: exportsApi.getQaTupleUrl(token),
      tupleFilename: 'qa-dataset-tuple.jsonl',
    },
    {
      title: 'Knowledge dataset',
      description:
        'Transcript chunks and report excerpts from your library, ready to feed into a model.',
      openaiUrl: exportsApi.getKnowledgeOpenaiUrl(token),
      openaiFilename: 'knowledge-dataset-openai.jsonl',
      tupleUrl: exportsApi.getKnowledgeTupleUrl(token),
      tupleFilename: 'knowledge-dataset-tuple.jsonl',
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
          Download your personal wiki as JSONL fine-tune datasets. Each set ships in two shapes: the OpenAI chat format and a plain tuple format.
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
              <Button
                variant="primary"
                onClick={() => handleDownload(card.openaiUrl, card.openaiFilename)}
              >
                OpenAI JSONL
              </Button>
              <Button
                variant="secondary"
                onClick={() => handleDownload(card.tupleUrl, card.tupleFilename)}
              >
                Tuple JSONL
              </Button>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
