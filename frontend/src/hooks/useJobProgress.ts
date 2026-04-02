import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { wsClient } from '../services/wsClient';
import type { Job } from '../types/job';
import type { WSProgressMessage } from '../types/ws';

export function useJobProgress(jobId: string | null) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!jobId) return;

    const unsubscribe = wsClient.subscribe(jobId, (msg: WSProgressMessage) => {
      // Update the specific job in cache
      queryClient.setQueryData(['job', jobId], (old: Job | undefined) => {
        if (!old) return old;
        return {
          ...old,
          status: msg.new_status ?? msg.status ?? old.status,
          progress_pct: msg.progress_pct ?? old.progress_pct,
          progress_message: msg.message ?? old.progress_message,
          error_message: msg.error ?? old.error_message,
        };
      });

      // Also update job in the list
      queryClient.setQueryData(['jobs', undefined], (old: Job[] | undefined) => {
        if (!old) return old;
        return old.map((j) =>
          j.id === jobId
            ? {
                ...j,
                status: msg.new_status ?? msg.status ?? j.status,
                progress_pct: msg.progress_pct ?? j.progress_pct,
                progress_message: msg.message ?? j.progress_message,
              }
            : j
        );
      });

      // Refresh on key status changes
      if (msg.type === 'job_status_change') {
        if (msg.new_status === 'awaiting_approval') {
          // Videos were just saved — refetch them for the approval list
          queryClient.invalidateQueries({ queryKey: ['jobVideos', jobId] });
        }
        if (msg.new_status === 'completed' || msg.new_status === 'failed') {
          queryClient.invalidateQueries({ queryKey: ['jobs'] });
          queryClient.invalidateQueries({ queryKey: ['job', jobId] });
          queryClient.invalidateQueries({ queryKey: ['jobVideos', jobId] });
        }
      }
    });

    return unsubscribe;
  }, [jobId, queryClient]);
}

export function useAllJobsProgress(jobIds: string[]) {
  const queryClient = useQueryClient();

  useEffect(() => {
    const unsubs = jobIds.map((jobId) =>
      wsClient.subscribe(jobId, (msg: WSProgressMessage) => {
        queryClient.setQueryData(['jobs', undefined], (old: Job[] | undefined) => {
          if (!old) return old;
          return old.map((j) =>
            j.id === jobId
              ? {
                  ...j,
                  status: msg.new_status ?? msg.status ?? j.status,
                  progress_pct: msg.progress_pct ?? j.progress_pct,
                  progress_message: msg.message ?? j.progress_message,
                }
              : j
          );
        });
      })
    );
    return () => unsubs.forEach((u) => u());
  }, [jobIds.join(','), queryClient]);
}
