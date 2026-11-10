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
 *
 * T-5.2.34: a copy the cache holds as ended takes no event
 * (`applyOutputProgress`), and an event that every cached copy drops is late,
 * so it refetches nothing, as `useJobProgress` does for a run.
 */
export function useOutputsProgress(outputIds: string[]) {
  const qc = useQueryClient();
  const key = [...outputIds].sort().join(',');

  useEffect(() => {
    if (!key) return;
    const ids = key.split(',');
    const unsubs = ids.map((id) =>
      wsClient.subscribe(id, (msg: WSProgressMessage) => {
        // How many cached copies of the output there are, and how many took
        // the event (an ended copy returns itself).
        let held = 0;
        let took = 0;
        const fold = <T extends OutputItem>(row: T): T => {
          held += 1;
          const next = applyOutputProgress(row, msg);
          if (next !== row) took += 1;
          return next;
        };

        qc.setQueriesData<OutputItem[]>({ queryKey: ['author', 'outputs'] }, (old) => {
          if (!Array.isArray(old)) return undefined;
          let changed = false;
          const next = old.map((row) => {
            if (row.id !== id) return row;
            const applied = fold(row);
            changed ||= applied !== row;
            return applied;
          });
          return changed ? next : undefined;
        });
        qc.setQueryData<OutputItem>(['author', 'output', id], (old) => {
          if (!old) return undefined;
          const applied = fold(old);
          return applied !== old ? applied : undefined;
        });

        const late = held > 0 && took === 0;
        if (!late && isTerminalMessage(msg)) {
          qc.invalidateQueries({ queryKey: ['author', 'outputs'] });
          qc.invalidateQueries({ queryKey: ['author', 'output', id] });
          qc.invalidateQueries({ queryKey: ['author', 'content', id] });
        }
      }),
    );
    return () => unsubs.forEach((u) => u());
  }, [key, qc]);
}
