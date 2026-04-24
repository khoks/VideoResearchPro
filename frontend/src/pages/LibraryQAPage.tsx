import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import {
  useAskLibraryQA,
  useClarifyLibraryQA,
  useLibraryQAHistory,
} from '../hooks/useLibraryQA';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import type { AnswerLanguage, LibraryQAExchange } from '../types/qa';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

const LANGUAGE_OPTIONS: Array<{ value: AnswerLanguage; label: string }> = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
];

export function LibraryQAPage() {
  const { data: history } = useLibraryQAHistory();
  const askQuestion = useAskLibraryQA();
  const clarifyQuestion = useClarifyLibraryQA();
  const libraryQAAvailable = useFeatureAvailable('library_qa');

  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');
  const [step, setStep] = useState<'ask' | 'clarify'>('ask');
  const [interpretation, setInterpretation] = useState('');
  const [clarifications, setClarifications] = useState<string[]>([]);
  const [clarificationAnswers, setClarificationAnswers] = useState<string[]>([]);

  const askInputDisabled = clarifyQuestion.isPending || !libraryQAAvailable;
  const askButtonDisabled = askInputDisabled || !question.trim();
  const clarifyButtonsDisabled = askQuestion.isPending || !libraryQAAvailable;

  const resetToAsk = () => {
    setStep('ask');
    setInterpretation('');
    setClarifications([]);
    setClarificationAnswers([]);
  };

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!question.trim() || !libraryQAAvailable) return;
    const result = await clarifyQuestion.mutateAsync({ question });
    setInterpretation(result.interpretation);
    setClarifications(result.clarifications);
    setClarificationAnswers(new Array(result.clarifications.length).fill(''));
    setStep('clarify');
  };

  const handleConfirmSearch = async () => {
    if (!libraryQAAvailable) return;
    const answeredParts = clarifications
      .map((q, i) => (clarificationAnswers[i]?.trim() ? `${q}\n${clarificationAnswers[i].trim()}` : null))
      .filter(Boolean) as string[];

    const context = [
      `My interpretation: ${interpretation}`,
      ...answeredParts,
    ].join('\n\n');

    await askQuestion.mutateAsync({ question, answer_language: language, context });
    setQuestion('');
    resetToAsk();
  };

  const handleSkipAndAsk = async () => {
    if (!libraryQAAvailable) return;
    await askQuestion.mutateAsync({ question, answer_language: language });
    setQuestion('');
    resetToAsk();
  };

  return (
    <div>
      <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                     boxShadow: '0 1px 3px rgba(0,0,0,0.08)', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0, color: '#1e293b' }}>Global Library Q&amp;A</h2>
        <p style={{ margin: '0.5rem 0 0', color: '#64748b', fontSize: '0.9rem' }}>
          Ask questions across every video in your library. Answers are grounded in the
          entire collected corpus with timestamped citations.
        </p>
      </div>

      <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                     boxShadow: '0 1px 3px rgba(0,0,0,0.08)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      marginBottom: '1rem', gap: '1rem', flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0, color: '#1e293b' }}>Ask Questions</h3>
          <label style={{ fontSize: '0.85rem', color: '#475569', display: 'flex',
                          alignItems: 'center', gap: '0.5rem' }}>
            Answer language:
            <select
              value={language}
              onChange={(e) => setLanguage(e.target.value as AnswerLanguage)}
              style={{
                padding: '0.4rem 0.6rem', borderRadius: 6, border: '1px solid #e2e8f0',
                fontSize: '0.85rem', background: '#fff',
              }}
            >
              {LANGUAGE_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </label>
        </div>

        {step === 'ask' && (
          <>
            {!libraryQAAvailable && (
              <p style={{ color: '#b45309', fontSize: '0.85rem', margin: '0 0 0.75rem' }}>
                {FEATURE_UNAVAILABLE_MSG}.
              </p>
            )}
            <form onSubmit={handleAsk} style={{ display: 'flex', gap: '0.5rem', marginBottom: '1rem' }}>
              <input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder={libraryQAAvailable
                  ? 'Ask a question about your entire library...'
                  : FEATURE_UNAVAILABLE_MSG}
                disabled={askInputDisabled}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
                style={{
                  flex: 1, padding: '0.6rem 1rem', borderRadius: 8, border: '1px solid #e2e8f0', fontSize: '0.95rem',
                  opacity: askInputDisabled ? 0.6 : 1,
                  background: askInputDisabled ? '#f1f5f9' : '#fff',
                }}
              />
              <button
                type="submit"
                disabled={askButtonDisabled}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
                style={{
                  background: '#667eea', color: '#fff', border: 'none', padding: '0.6rem 1.5rem',
                  borderRadius: 8, cursor: askButtonDisabled ? 'not-allowed' : 'pointer',
                  fontWeight: 600, opacity: askButtonDisabled ? 0.5 : 1,
                }}
              >
                {clarifyQuestion.isPending ? '...' : 'Ask'}
              </button>
            </form>
            {clarifyQuestion.isPending && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '1rem',
                            padding: '1rem', background: '#f0f2ff', borderRadius: 8 }}>
                <LoadingSpinner size={20} />
                <span style={{ color: '#667eea', fontSize: '0.9rem', fontWeight: 500 }}>
                  Generating clarifying questions...
                </span>
              </div>
            )}
          </>
        )}

        {step === 'clarify' && (
          <div style={{ marginBottom: '1.5rem', padding: '1.25rem', background: '#f8fafc',
                        borderRadius: 10, border: '1px solid #e2e8f0' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                          marginBottom: '0.75rem' }}>
              <p style={{ margin: 0, fontSize: '0.8rem', color: '#94a3b8', fontWeight: 500 }}>
                Your question: <em style={{ color: '#64748b' }}>{question}</em>
              </p>
              <button onClick={resetToAsk} style={{
                background: 'none', border: 'none', color: '#94a3b8', cursor: 'pointer',
                fontSize: '0.8rem', padding: 0, flexShrink: 0, marginLeft: '1rem',
              }}>
                ← Edit question
              </button>
            </div>

            <div style={{ marginBottom: '1rem', padding: '0.75rem', background: '#eef2ff',
                          borderRadius: 8, borderLeft: '3px solid #667eea' }}>
              <p style={{ margin: 0, fontSize: '0.85rem', fontWeight: 600, color: '#4338ca',
                          marginBottom: '0.25rem' }}>Here's how I understand your question:</p>
              <p style={{ margin: 0, fontSize: '0.9rem', color: '#334155', lineHeight: 1.5 }}>
                {interpretation}
              </p>
            </div>

            {clarifications.length > 0 && (
              <div style={{ marginBottom: '1rem' }}>
                <p style={{ margin: '0 0 0.5rem', fontSize: '0.85rem', fontWeight: 600, color: '#475569' }}>
                  A few clarifying questions (optional — answer any that are useful):
                </p>
                {clarifications.map((q, i) => (
                  <div key={i} style={{ marginBottom: '0.75rem' }}>
                    <label style={{ display: 'block', fontSize: '0.85rem', color: '#475569',
                                     marginBottom: '0.25rem' }}>
                      {q}
                    </label>
                    <input
                      value={clarificationAnswers[i] ?? ''}
                      onChange={(e) => {
                        const next = [...clarificationAnswers];
                        next[i] = e.target.value;
                        setClarificationAnswers(next);
                      }}
                      placeholder="Your answer (optional)"
                      disabled={askQuestion.isPending}
                      style={{
                        width: '100%', padding: '0.5rem 0.75rem', borderRadius: 6,
                        border: '1px solid #e2e8f0', fontSize: '0.875rem', boxSizing: 'border-box',
                        background: askQuestion.isPending ? '#f1f5f9' : '#fff',
                      }}
                    />
                  </div>
                ))}
              </div>
            )}

            {askQuestion.isPending && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', marginBottom: '0.75rem',
                            padding: '0.75rem', background: '#f0f2ff', borderRadius: 8 }}>
                <LoadingSpinner size={18} />
                <span style={{ color: '#667eea', fontSize: '0.9rem', fontWeight: 500 }}>
                  Searching the library and generating answer...
                </span>
              </div>
            )}

            <div style={{ display: 'flex', gap: '0.5rem' }}>
              <button
                onClick={handleConfirmSearch}
                disabled={clarifyButtonsDisabled}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
                style={{
                  background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  color: '#fff', border: 'none', padding: '0.6rem 1.25rem',
                  borderRadius: 8, cursor: clarifyButtonsDisabled ? 'not-allowed' : 'pointer',
                  fontWeight: 600, fontSize: '0.9rem',
                  opacity: clarifyButtonsDisabled ? 0.6 : 1,
                }}
              >
                {askQuestion.isPending ? '...' : 'Confirm & Search'}
              </button>
              <button
                onClick={handleSkipAndAsk}
                disabled={clarifyButtonsDisabled}
                title={!libraryQAAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
                style={{
                  background: 'none', color: '#667eea', border: '1px solid #667eea',
                  padding: '0.6rem 1.25rem', borderRadius: 8,
                  cursor: clarifyButtonsDisabled ? 'not-allowed' : 'pointer',
                  fontWeight: 500, fontSize: '0.9rem',
                  opacity: clarifyButtonsDisabled ? 0.4 : 1,
                }}
              >
                Skip clarifications
              </button>
            </div>
          </div>
        )}

        {history && history.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem',
                        marginTop: step === 'clarify' ? 0 : '1rem' }}>
            {history.map(qa => (
              <LibraryQAExchangeCard key={qa.id} qa={qa} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function LibraryQAExchangeCard({ qa }: { qa: LibraryQAExchange }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(qa.answer);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (e.g. insecure context) — leave button state unchanged
    }
  };

  return (
    <div style={{ padding: '1rem', background: '#f8fafc', borderRadius: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
                    gap: '0.75rem', marginBottom: '0.5rem' }}>
        <p style={{ fontWeight: 600, color: '#1e293b', margin: 0, flex: 1 }}>Q: {qa.question}</p>
        <button onClick={handleCopy} style={{
          background: copied ? '#22c55e' : '#fff', color: copied ? '#fff' : '#475569',
          border: '1px solid #cbd5e1', padding: '0.25rem 0.6rem', borderRadius: 6,
          cursor: 'pointer', fontSize: '0.75rem', fontWeight: 500, flexShrink: 0,
        }}>
          {copied ? 'Copied' : 'Copy answer'}
        </button>
      </div>
      <div style={{ color: '#334155', lineHeight: 1.6 }}>
        <ReactMarkdown>{qa.answer}</ReactMarkdown>
      </div>
      {qa.references.length > 0 && (
        <div style={{ marginTop: '0.75rem', borderTop: '1px solid #e2e8f0', paddingTop: '0.5rem' }}>
          <span style={{ fontSize: '0.8rem', fontWeight: 600, color: '#64748b' }}>References:</span>
          {qa.references.map((ref, i) => (
            <div key={i} style={{ fontSize: '0.8rem', color: '#667eea', marginTop: '0.25rem' }}>
              <a href={ref.youtube_link} target="_blank" rel="noopener noreferrer"
                 style={{ color: '#667eea', textDecoration: 'none' }}>
                {ref.video_title} by {ref.channel_name} at {ref.timestamp_display}
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
