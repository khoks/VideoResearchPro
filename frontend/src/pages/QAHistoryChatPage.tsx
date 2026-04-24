import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { LoadingSpinner } from '../components/common/LoadingSpinner';
import {
  useAskQAHistoryChat,
  useQAHistoryChatHistory,
} from '../hooks/useQAHistoryChat';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import type {
  AnswerLanguage,
  QAHistoryExchange,
  QAHistoryReference,
} from '../types/qa';

const FEATURE_UNAVAILABLE_MSG = 'LLM-dependent feature is temporarily unavailable';

const LANGUAGE_OPTIONS: Array<{ value: AnswerLanguage; label: string }> = [
  { value: 'en', label: 'English' },
  { value: 'hi', label: 'हिन्दी' },
  { value: 'es', label: 'Español' },
  { value: 'fr', label: 'Français' },
];

// Build the href for a reference back to its source Q&A location.
// The "history" source deep-links back to this same page, keyed by exchange id.
function referenceHref(ref: QAHistoryReference): string {
  if (ref.source_type === 'job' && ref.job_id) {
    return `/jobs/${ref.job_id}`;
  }
  if (ref.source_type === 'library') {
    return '/library/qa';
  }
  return `/qa-history#exchange-${ref.exchange_id}`;
}

function referenceSourceLabel(ref: QAHistoryReference): string {
  switch (ref.source_type) {
    case 'job':
      return 'Job Q&A';
    case 'library':
      return 'Global Q&A';
    case 'history':
      return 'Q&A History';
  }
}

export function QAHistoryChatPage() {
  const { data: history, isLoading } = useQAHistoryChatHistory();
  const askChat = useAskQAHistoryChat();
  const qaHistoryAvailable = useFeatureAvailable('qa_history');

  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');

  const inputDisabled = askChat.isPending || !qaHistoryAvailable;
  const buttonDisabled = inputDisabled || !question.trim();

  // The page renders history ascending (oldest at top) so the newest exchange
  // lands at the bottom — chat-style. After a new answer arrives or on first
  // load with a #exchange-<id> hash we scroll it into view.
  const historyEndRef = useRef<HTMLDivElement | null>(null);
  const sortedHistory = useMemo(() => {
    if (!history) return [];
    return [...history].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  }, [history]);

  useEffect(() => {
    if (!sortedHistory.length) return;
    // Honor deep-link hash (#exchange-<id>) exactly once per load; otherwise
    // stick to the chat-style "scroll to newest" behavior.
    const hash = window.location.hash;
    if (hash.startsWith('#exchange-')) {
      const el = document.getElementById(hash.slice(1));
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' });
        return;
      }
    }
    historyEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [sortedHistory.length]);

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = question.trim();
    if (!trimmed || askChat.isPending || !qaHistoryAvailable) return;
    await askChat.mutateAsync({ question: trimmed, answer_language: language });
    setQuestion('');
  };

  return (
    <div>
      <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                     boxShadow: '0 1px 3px rgba(0,0,0,0.08)', marginBottom: '1rem' }}>
        <h2 style={{ margin: 0, color: '#1e293b' }}>Chat with your Q&amp;A History</h2>
        <p style={{ margin: '0.5rem 0 0', color: '#64748b', fontSize: '0.9rem' }}>
          Ask meta-questions across every Q&amp;A you&apos;ve ever run — job-scoped, global,
          and previous history chats. Answers cite the original exchanges so you can jump
          back to the source.
        </p>
      </div>

      <div style={{ background: '#fff', borderRadius: 12, padding: '1.5rem',
                     boxShadow: '0 1px 3px rgba(0,0,0,0.08)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                      marginBottom: '1rem', gap: '1rem', flexWrap: 'wrap' }}>
          <h3 style={{ margin: 0, color: '#1e293b' }}>History Chat</h3>
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

        {isLoading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '1.5rem' }}>
            <LoadingSpinner size={28} />
          </div>
        )}

        {!isLoading && sortedHistory.length === 0 && (
          <p style={{ color: '#94a3b8', fontSize: '0.9rem', margin: '0 0 1rem' }}>
            No history yet — ask your first meta-question below.
          </p>
        )}

        {sortedHistory.length > 0 && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem',
                        marginBottom: '1rem' }}>
            {sortedHistory.map(qa => (
              <QAHistoryExchangeCard key={qa.id} qa={qa} />
            ))}
            <div ref={historyEndRef} />
          </div>
        )}

        {askChat.isPending && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem',
                        marginBottom: '1rem', padding: '1rem', background: '#f0f2ff',
                        borderRadius: 8 }}>
            <LoadingSpinner size={20} />
            <span style={{ color: '#667eea', fontSize: '0.9rem', fontWeight: 500 }}>
              Searching your Q&amp;A history and generating answer...
            </span>
          </div>
        )}

        {!qaHistoryAvailable && (
          <p style={{ color: '#b45309', fontSize: '0.85rem', margin: '0 0 0.5rem' }}>
            {FEATURE_UNAVAILABLE_MSG}.
          </p>
        )}
        <form onSubmit={handleAsk} style={{ display: 'flex', gap: '0.5rem' }}>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder={qaHistoryAvailable
              ? "Ask across every Q&A you've ever run..."
              : FEATURE_UNAVAILABLE_MSG}
            disabled={inputDisabled}
            title={!qaHistoryAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
            style={{
              flex: 1, padding: '0.6rem 1rem', borderRadius: 8, border: '1px solid #e2e8f0',
              fontSize: '0.95rem',
              opacity: inputDisabled ? 0.6 : 1,
              background: inputDisabled ? '#f1f5f9' : '#fff',
            }}
          />
          <button
            type="submit"
            disabled={buttonDisabled}
            title={!qaHistoryAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
            style={{
              background: '#667eea', color: '#fff', border: 'none', padding: '0.6rem 1.5rem',
              borderRadius: 8,
              cursor: buttonDisabled ? 'not-allowed' : 'pointer',
              fontWeight: 600, opacity: buttonDisabled ? 0.5 : 1,
            }}
          >
            {askChat.isPending ? '...' : 'Ask'}
          </button>
        </form>
      </div>
    </div>
  );
}

function QAHistoryExchangeCard({ qa }: { qa: QAHistoryExchange }) {
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
    <div id={`exchange-${qa.id}`} style={{ padding: '1rem', background: '#f8fafc', borderRadius: 8 }}>
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
            <div key={i} style={{ fontSize: '0.8rem', marginTop: '0.25rem' }}>
              <a href={referenceHref(ref)}
                 style={{ color: '#667eea', textDecoration: 'none' }}>
                [{referenceSourceLabel(ref)}] {ref.question_preview}
              </a>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
