import { useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import {
  useAskQAHistoryChat,
  useQAHistoryChatHistory,
} from '../hooks/useQAHistoryChat';
import { useFeatureAvailable } from '../hooks/useFeatureAvailable';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Select,
  Spinner,
} from '../components/primitives';
import { useColors } from '../hooks/useTheme';
import {
  fonts,
  fontSize,
  fontWeight,
  lineHeight,
  measure,
  radius,
  space,
} from '../theme';
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
      return 'Echo chat';
  }
}

export function QAHistoryChatPage() {
  const c = useColors();
  const { data: history, isLoading } = useQAHistoryChatHistory();
  const askChat = useAskQAHistoryChat();
  const qaHistoryAvailable = useFeatureAvailable('qa_history');

  const [question, setQuestion] = useState('');
  const [language, setLanguage] = useState<AnswerLanguage>('en');

  const inputDisabled = askChat.isPending || !qaHistoryAvailable;
  const buttonDisabled = inputDisabled || !question.trim();

  const historyEndRef = useRef<HTMLDivElement | null>(null);
  const sortedHistory = useMemo(() => {
    if (!history) return [];
    return [...history].sort(
      (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
    );
  }, [history]);

  useEffect(() => {
    if (!sortedHistory.length) return;
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
          Echoes of past questions
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
          Ask meta-questions across every Q&amp;A you've ever run — job-scoped, global, and previous chats. Answers cite the original exchanges so you can jump back to the source.
        </p>
      </header>

      <Card>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: space['4'],
            flexWrap: 'wrap',
            marginBottom: space['4'],
          }}
        >
          <h2
            style={{
              margin: 0,
              fontFamily: fonts.display,
              fontSize: fontSize.lg,
              fontWeight: fontWeight.semibold,
              color: c.textPrimary,
            }}
          >
            Chat
          </h2>
          <label
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: space['2'],
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
              color: c.textSecondary,
            }}
          >
            Answer language
            <Select
              value={language}
              onChange={(e) => setLanguage(e.target.value as AnswerLanguage)}
              style={{ width: 'auto', minWidth: 140 }}
            >
              {LANGUAGE_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </Select>
          </label>
        </div>

        {isLoading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: space['6'] }}>
            <Spinner size={28} />
          </div>
        )}

        {!isLoading && sortedHistory.length === 0 && (
          <EmptyState
            size="sm"
            title="No echoes yet."
            description="Ask your first meta-question below to begin."
          />
        )}

        {sortedHistory.length > 0 && (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: space['3'],
              marginBottom: space['4'],
            }}
          >
            {sortedHistory.map((qa) => (
              <QAHistoryExchangeCard key={qa.id} qa={qa} />
            ))}
            <div ref={historyEndRef} />
          </div>
        )}

        {askChat.isPending && (
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: space['3'],
              marginBottom: space['3'],
              padding: space['3'],
              background: c.accentSubtle,
              borderRadius: radius.md,
            }}
          >
            <Spinner size={16} />
            <span
              style={{
                fontFamily: fonts.ui,
                fontSize: fontSize.sm,
                color: c.accent,
                fontWeight: fontWeight.medium,
              }}
            >
              Searching your Q&amp;A history and generating answer…
            </span>
          </div>
        )}

        {!qaHistoryAvailable && (
          <div
            role="alert"
            style={{
              marginBottom: space['3'],
              padding: space['3'],
              borderRadius: radius.md,
              background: c.warnSubtle,
              border: `1px solid ${c.warn}`,
              color: c.warn,
              fontFamily: fonts.ui,
              fontSize: fontSize.sm,
            }}
          >
            {FEATURE_UNAVAILABLE_MSG}.
          </div>
        )}

        <form
          onSubmit={handleAsk}
          style={{ display: 'flex', gap: space['2'], flexWrap: 'wrap' }}
        >
          <div style={{ flex: '1 1 280px' }}>
            <Input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={
                qaHistoryAvailable
                  ? "Ask across every Q&A you've ever run…"
                  : FEATURE_UNAVAILABLE_MSG
              }
              disabled={inputDisabled}
              title={!qaHistoryAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
              aria-label="Question"
            />
          </div>
          <Button
            type="submit"
            disabled={buttonDisabled}
            loading={askChat.isPending}
            title={!qaHistoryAvailable ? FEATURE_UNAVAILABLE_MSG : undefined}
          >
            Ask
          </Button>
        </form>
      </Card>
    </div>
  );
}

function QAHistoryExchangeCard({ qa }: { qa: QAHistoryExchange }) {
  const c = useColors();
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
    <div
      id={`exchange-${qa.id}`}
      style={{
        padding: space['4'],
        background: c.surfaceAlt,
        borderRadius: radius.md,
        border: `1px solid ${c.border}`,
      }}
    >
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          gap: space['3'],
          marginBottom: space['3'],
        }}
      >
        <p
          style={{
            margin: 0,
            flex: 1,
            fontFamily: fonts.display,
            fontSize: fontSize.md,
            fontWeight: fontWeight.semibold,
            color: c.textPrimary,
            lineHeight: lineHeight.snug,
          }}
        >
          {qa.question}
        </p>
        <Button size="sm" variant="tertiary" onClick={handleCopy}>
          {copied ? (
            <Badge tone="success" size="sm">
              Copied
            </Badge>
          ) : (
            'Copy answer'
          )}
        </Button>
      </div>
      <div
        className="reading"
        style={{
          color: c.textPrimary,
          fontFamily: fonts.body,
          fontSize: fontSize.base,
          lineHeight: lineHeight.loose,
        }}
      >
        <ReactMarkdown>{qa.answer}</ReactMarkdown>
      </div>
      {qa.references.length > 0 && (
        <div
          style={{
            marginTop: space['3'],
            borderTop: `1px solid ${c.border}`,
            paddingTop: space['3'],
          }}
        >
          <span
            style={{
              fontFamily: fonts.ui,
              fontSize: fontSize.xs,
              fontWeight: fontWeight.semibold,
              color: c.textSecondary,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            References
          </span>
          <div
            style={{
              marginTop: space['2'],
              display: 'flex',
              flexDirection: 'column',
              gap: space['1'],
            }}
          >
            {qa.references.map((ref, i) => (
              <a
                key={i}
                href={referenceHref(ref)}
                style={{
                  fontFamily: fonts.ui,
                  fontSize: fontSize.sm,
                  color: c.accent,
                  textDecoration: 'none',
                }}
              >
                <span
                  style={{
                    color: c.textMuted,
                    fontSize: fontSize.xs,
                    marginRight: space['2'],
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  {referenceSourceLabel(ref)}
                </span>
                {ref.question_preview}
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
