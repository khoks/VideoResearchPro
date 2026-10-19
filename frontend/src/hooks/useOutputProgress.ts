import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { wsClient } from '../services/wsClient';
import type { OutputItem } from '../services/authorApi';
import type { WSProgressMessage } from '../types/ws';
import { applyOutputProgress, isTerminalMessage } from '../utils/authorOutputs';

/**
 * S-6.7.1: live progress for Author Studio outputs. The worker publishes on
 * `job_progress:{output_id}`, the channel jobs use, so this rides the same
 * socket as `useJobProgress`. Each message is folded into every cached
 * outputs list and the single-output query; a terminal status refetches them
 * (and the content) so a finished book is readable without a reload.
 */
export function useOutputsProgress(outputIds: string[]) {
  const qc = useQueryClient();
  const key = [...outputIds].sort().join(',');

  useEffect(() => {
    if (!key) return;
    const ids = key.split(',');
    const unsubs = ids.map((id) =>
      wsClient.subscribe(id, (msg: WSProgressMessage) => {
        qc.setQueriesData<OutputItem[]>({ queryKey: ['author', 'outputs'] }, (old) =>
          old ? old.map((row) => applyOutputProgress(row, msg)) : old,
        );
        qc.setQueryData<OutputItem>(['author', 'output', id], (old) => (old ? applyOutputProgress(old, msg) : old));
        if (isTerminalMessage(msg)) {
          qc.invalidateQueries({ queryKey: ['author', 'outputs'] });
          qc.invalidateQueries({ queryKey: ['author', 'output', id] });
          qc.invalidateQueries({ queryKey: ['author', 'content', id] });
        }
      }),
    );
    return () => unsubs.forEach((u) => u());
  }, [key, qc]);
}
