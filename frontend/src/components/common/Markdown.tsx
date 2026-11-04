/**
 * Renders Markdown on the app's pages: Q&A answers, notes, knowledge reports.
 * Every page imports this, never `react-markdown`, so the renderer and the
 * unified stack under it stay out of the main chunk (T-8.8.4.5).
 *
 * Until the chunk arrives the text is on the page already, in the same
 * elements, so nothing waits on a spinner and nothing moves when the real
 * render replaces it. If the chunk cannot load (a deploy replaced it, the
 * network dropped) the plain text stays: an answer that loses its bold is
 * better than an error screen over a page that loaded.
 */
import { lazy, Suspense } from 'react';
import { markdownBlocks, type MarkdownBlock } from '../../utils/markdownBlocks';

function Text({ children }: { children: string }) {
  return (
    <>
      {children.split('**').map((run, i) => (i % 2 === 1 ? <strong key={i}>{run}</strong> : run))}
    </>
  );
}

function Block({ block }: { block: MarkdownBlock }) {
  switch (block.kind) {
    case 'heading': {
      const Heading = `h${block.level}` as const;
      return (
        <Heading>
          <Text>{block.text}</Text>
        </Heading>
      );
    }
    case 'list': {
      const List = block.ordered ? 'ol' : 'ul';
      return (
        <List>
          {block.items.map((item, i) => (
            <li key={i}>
              <Text>{item}</Text>
            </li>
          ))}
        </List>
      );
    }
    case 'code':
      return (
        <pre>
          <code>{block.text}</code>
        </pre>
      );
    case 'paragraph':
      return (
        <p>
          <Text>{block.text}</Text>
        </p>
      );
  }
}

function PlainMarkdown({ children }: { children?: string | null }) {
  return (
    <>
      {markdownBlocks(children ?? '').map((block, i) => (
        <Block key={i} block={block} />
      ))}
    </>
  );
}

const ReactMarkdown = lazy(() => import('react-markdown').catch(() => ({ default: PlainMarkdown })));

export function Markdown({ children }: { children: string }) {
  return (
    <Suspense fallback={<PlainMarkdown>{children}</PlainMarkdown>}>
      <ReactMarkdown>{children}</ReactMarkdown>
    </Suspense>
  );
}
