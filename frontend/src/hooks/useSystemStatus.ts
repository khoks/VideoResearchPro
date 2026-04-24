import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import api from '../services/api';
import { useSystemStatusStore, type LLMStatus } from '../stores/systemStatusStore';

interface HealthLLMPayload {
  status?: LLMStatus;
  unavailable_features?: string[];
  last_checked_at?: number;
}

interface HealthResponse {
  llm?: HealthLLMPayload;
}

interface NormalizedHealth {
  status: LLMStatus;
  unavailableFeatures: string[];
  checkedAt: number;
}

async function fetchHealth(): Promise<NormalizedHealth> {
  const { data } = await api.get<HealthResponse>('/health');
  // Graceful degradation: if Unit 1 hasn't merged yet, `llm` is absent —
  // treat as healthy so gated features stay enabled.
  const llm = data.llm ?? {};
  return {
    status: llm.status ?? 'ok',
    unavailableFeatures: llm.unavailable_features ?? [],
    checkedAt: Date.now(),
  };
}

export function useSystemStatus() {
  const setStatus = useSystemStatusStore((s) => s.setStatus);

  const query = useQuery({
    queryKey: ['systemStatus'],
    queryFn: fetchHealth,
    refetchInterval: 60_000,
    refetchOnWindowFocus: true,
    // The health endpoint itself never throws a toast — a transient 5xx
    // should not spam the user — so we leave errors quiet.
    retry: 1,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!query.data) return;
    setStatus(query.data.status, query.data.unavailableFeatures, query.data.checkedAt);
  }, [query.data, setStatus]);

  return { refetch: query.refetch };
}
