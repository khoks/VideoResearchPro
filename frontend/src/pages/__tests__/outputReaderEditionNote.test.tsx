/**
 * T-6.1.3.7 at the reader: a book's "About this edition" note is the first long
 * paragraph of a cohesive book, so it took the section's drop cap. It is a note
 * about the book, and the drop cap belongs to the book's own first paragraph.
 * The manuscript here has the shape `book_markdown.py` writes.
 */
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { OutputItem } from '../../services/authorApi';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const BODY = 'Tides move more water in a day than every river on earth moves in a year, and the first engineers to notice built their mills beside the estuaries.';
const MANUSCRIPT = `# Tidal energy

_Authored by Pratidhvani Author Studio — 2026-11-04_

_Compiled from 2 sources in your library._

_About this edition: the introduction, chapter bridges, conclusion and glossary were written by a model (gpt-5.4) from the chapters. Each chapter is its run's report, unchanged, with its own citations._

_Processing note: one chapter's report had no citations, so the glossary leaves it out of the terms it lists for each chapter._

## Table of Contents

- [Introduction](#introduction)

## Introduction

${BODY}

A second paragraph, as long as the first one needs to be for the drop cap rule to have a choice to make here.
`;

const OUTPUT = {
  id: 'o1',
  kind: 'book',
  title: 'Tidal energy',
  status: 'completed',
  source_ids: ['j1'],
  parameters: {},
  error_message: null,
  created_at: '2026-11-04T10:00:00Z',
  updated_at: '2026-11-04T10:00:00Z',
  has_content: true,
  formats: ['md'],
  citation_count: 0,
} as unknown as OutputItem;

vi.mock('../../services/api', () => ({
  default: {
    get: async (path: string) => {
      if (path === '/author/outputs/o1') return { data: OUTPUT };
      if (path === '/author/outputs/o1/content') return { data: MANUSCRIPT };
      throw Object.assign(new Error('no fixture'), { response: { status: 404 } });
    },
    defaults: { baseURL: 'http://localhost:8000/api/v1' },
  },
}));
vi.mock('../../hooks/useOutputProgress', () => ({ useOutputsProgress: () => undefined }));

import { OutputReaderPage } from '../OutputReaderPage';

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
});

async function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  act(() =>
    root.render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/author/outputs/o1']}>
          <Routes>
            <Route path="/author/outputs/:outputId" element={<OutputReaderPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  );
  for (let i = 0; i < 8; i++) {
    await act(async () => {
      await new Promise((r) => setTimeout(r, 0));
    });
  }
}

describe('the reader on a book with an edition note', () => {
  it('leaves the note a note and gives the drop cap to the book itself', async () => {
    await mount();
    const caps = Array.from(host.querySelectorAll('.reader-dropcap'));
    expect(caps).toHaveLength(1);
    expect(caps[0].textContent).toBe(BODY);

    const note = Array.from(host.querySelectorAll('p')).find((p) => p.textContent?.startsWith('About this edition'));
    expect(note, 'the note stays on the page').toBeDefined();
    expect(note!.classList.contains('reader-dropcap')).toBe(false);
    expect(note!.firstElementChild?.tagName).toBe('EM');
  });
});
