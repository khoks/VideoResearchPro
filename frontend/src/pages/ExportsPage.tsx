import { useAuth } from '../contexts/AuthContext';
import { useJobStore } from '../stores/jobStore';
import { exportsApi } from '../services/exportsApi';
import { downloadUrl } from '../utils/download';

interface DatasetCard {
  title: string;
  description: string;
  openaiUrl: string;
  openaiFilename: string;
  tupleUrl: string;
  tupleFilename: string;
}

export function ExportsPage() {
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
    <div style={{ maxWidth: 960, margin: '0 auto', padding: '2rem 1rem' }}>
      <h2 style={{ margin: '0 0 0.5rem', color: 'var(--color-text)' }}>Exports</h2>
      <p style={{ margin: '0 0 2rem', color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
        Download your personal wiki as JSONL fine-tune datasets. Each dataset is offered in
        two shapes: the OpenAI chat format and a plain tuple format.
      </p>

      <div style={{ display: 'grid', gap: '1.25rem' }}>
        {cards.map((c) => (
          <section
            key={c.title}
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 12,
              padding: '1.25rem 1.5rem',
              boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
            }}
          >
            <h3 style={{ margin: '0 0 0.4rem', color: 'var(--color-text)', fontSize: '1.1rem' }}>
              {c.title}
            </h3>
            <p style={{ margin: '0 0 1rem', color: 'var(--color-text-muted)', lineHeight: 1.45 }}>
              {c.description}
            </p>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.6rem' }}>
              <DownloadButton
                label="OpenAI JSONL"
                onClick={() => handleDownload(c.openaiUrl, c.openaiFilename)}
              />
              <DownloadButton
                label="Tuple JSONL"
                onClick={() => handleDownload(c.tupleUrl, c.tupleFilename)}
                variant="secondary"
              />
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

function DownloadButton({
  label,
  onClick,
  variant = 'primary',
}: {
  label: string;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
}) {
  const isPrimary = variant === 'primary';
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        background: isPrimary ? '#667eea' : 'transparent',
        color: isPrimary ? '#fff' : 'var(--color-text)',
        border: isPrimary ? 'none' : '1px solid var(--color-border)',
        padding: '0.55rem 1.1rem',
        borderRadius: 8,
        cursor: 'pointer',
        fontWeight: 600,
        fontSize: '0.9rem',
      }}
    >
      {label}
    </button>
  );
}
