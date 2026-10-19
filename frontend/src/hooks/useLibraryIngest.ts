import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { libraryApi, type UploadPdfResponse } from '../services/libraryApi';
import { describeUploadError, isPdfFile } from '../utils/ingestResults';

export type UploadItemStatus = 'queued' | 'uploading' | 'done' | 'error';

export interface UploadItem {
  id: string;
  file: File;
  status: UploadItemStatus;
  /** 0..1 bytes sent. Reaches 1 before the server finishes extracting. */
  progress: number;
  result?: UploadPdfResponse;
  error?: string;
}

let uploadCounter = 0;

/**
 * Sequential upload queue for PDFs. One file in flight at a time: the
 * endpoint extracts and embeds synchronously, so parallel uploads only
 * pile CPU work onto the API process. The library list is invalidated
 * once the queue drains.
 */
export function usePdfUploadQueue() {
  const qc = useQueryClient();
  const [items, setItems] = useState<UploadItem[]>([]);
  const hadWorkRef = useRef(false);

  const enqueue = useCallback((files: File[]) => {
    if (files.length === 0) return;
    const next: UploadItem[] = files.map((file) => {
      uploadCounter += 1;
      const id = `upload-${uploadCounter}`;
      if (!isPdfFile(file)) {
        return { id, file, status: 'error', progress: 0, error: 'Not a .pdf file.' };
      }
      return { id, file, status: 'queued', progress: 0 };
    });
    setItems((prev) => [...prev, ...next]);
  }, []);

  /** Drop a row from the list. An in-flight upload cannot be cancelled. */
  const remove = useCallback((id: string) => {
    setItems((prev) => prev.filter((i) => i.id !== id || i.status === 'uploading'));
  }, []);

  const clearFinished = useCallback(() => {
    setItems((prev) => prev.filter((i) => i.status === 'queued' || i.status === 'uploading'));
  }, []);

  useEffect(() => {
    if (items.some((i) => i.status === 'uploading')) return;
    const next = items.find((i) => i.status === 'queued');
    if (!next) {
      if (hadWorkRef.current) {
        hadWorkRef.current = false;
        qc.invalidateQueries({ queryKey: ['libraryVideos'] });
      }
      return;
    }
    hadWorkRef.current = true;
    const patch = (id: string, changes: Partial<UploadItem>) =>
      setItems((prev) => prev.map((i) => (i.id === id ? { ...i, ...changes } : i)));

    patch(next.id, { status: 'uploading', progress: 0 });
    libraryApi
      .uploadPdf(next.file, (fraction) => patch(next.id, { progress: fraction }))
      .then((result) => patch(next.id, { status: 'done', progress: 1, result }))
      .catch((err: unknown) =>
        patch(next.id, { status: 'error', error: describeUploadError(err as Parameters<typeof describeUploadError>[0]) }),
      );
  }, [items, qc]);

  const isBusy = items.some((i) => i.status === 'queued' || i.status === 'uploading');

  return { items, enqueue, remove, clearFinished, isBusy };
}

export function usePasteUrls() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (urls: string[]) => libraryApi.pasteUrls(urls),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['libraryVideos'] }),
  });
}
