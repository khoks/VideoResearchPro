/*
 * AI-model user settings — React Query bindings for /settings/llm.
 *
 * Contract (backend, E-5.x "AI models" panel):
 *   GET    /settings/llm                → LLMSettingsResponse (registry + per-user overrides)
 *   PUT    /settings/llm/{use_case}     → set override {provider, model, reasoning}
 *   DELETE /settings/llm/{use_case}     → clear override (revert to default)
 *   POST   /settings/llm/estimate       → cost projection against the benchmark job.
 *                                         `overrides` is a partial map; omitted use cases
 *                                         fall back to the saved effective config.
 *
 * Flow is immediate-save: a select change PUTs right away with an optimistic
 * cache update (rolled back on error — the global MutationCache in App.tsx
 * owns the error toast). After each save the estimate is re-fetched with an
 * empty overrides map, debounced 500 ms so a burst of edits costs one call.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query';
import api from '../services/api';

// ── Contract types ────────────────────────────────────────────────

export interface LLMConfig {
  provider: string;
  model: string;
  reasoning: string;
}

export interface LLMUseCase {
  use_case: string;
  summary: string;
  group: string;
  default: LLMConfig;
  override: LLMConfig | null;
  effective: LLMConfig;
  typical_input_tokens: number;
  typical_output_tokens: number;
}

export interface LLMModelInfo {
  id: string;
  context_window: number;
}

export interface LLMSettingsResponse {
  use_cases: LLMUseCase[];
  providers: Record<string, { models: LLMModelInfo[] }>;
  reasoning_levels: string[];
}

export interface EstimateBenchmark {
  label: string;
  videos: number;
  transcript_words: number;
  questions_assumed: number;
  knowledge_videos_assumed: number;
}

export interface EstimateRow {
  use_case: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  pricing_known: boolean;
}

export interface EstimateResponse {
  benchmark: EstimateBenchmark;
  per_use_case: EstimateRow[];
  totals: {
    cost_usd: number;
    unknown_pricing_models: string[];
  };
}

// ── Query keys ────────────────────────────────────────────────────

export const LLM_SETTINGS_KEY = ['llm-settings'] as const;
export const LLM_ESTIMATE_KEY = ['llm-estimate'] as const;

// ── Queries ───────────────────────────────────────────────────────

export function useLLMSettings() {
  return useQuery<LLMSettingsResponse>({
    queryKey: LLM_SETTINGS_KEY,
    queryFn: async () => {
      const { data } = await api.get<LLMSettingsResponse>('/settings/llm');
      return data;
    },
    staleTime: 60_000,
  });
}

/**
 * Cost projection for the benchmark job under the *saved* effective config.
 * Overrides map is empty because saves land immediately (see module docstring);
 * the query is invalidated (debounced) after every successful save.
 */
export function useLLMEstimate(enabled = true) {
  return useQuery<EstimateResponse>({
    queryKey: LLM_ESTIMATE_KEY,
    queryFn: async () => {
      const { data } = await api.post<EstimateResponse>('/settings/llm/estimate', {
        overrides: {},
      });
      return data;
    },
    enabled,
    staleTime: 30_000,
  });
}

// ── Debounced estimate refresh ────────────────────────────────────

const ESTIMATE_DEBOUNCE_MS = 500;
let estimateTimer: ReturnType<typeof setTimeout> | undefined;

function invalidateEstimateDebounced(queryClient: QueryClient) {
  if (estimateTimer) clearTimeout(estimateTimer);
  estimateTimer = setTimeout(() => {
    estimateTimer = undefined;
    void queryClient.invalidateQueries({ queryKey: LLM_ESTIMATE_KEY });
  }, ESTIMATE_DEBOUNCE_MS);
}

// ── Optimistic cache helpers ──────────────────────────────────────

type MutationContext = { previous: LLMSettingsResponse | undefined };

function patchUseCase(
  data: LLMSettingsResponse,
  useCase: string,
  patch: (uc: LLMUseCase) => LLMUseCase,
): LLMSettingsResponse {
  return {
    ...data,
    use_cases: data.use_cases.map((uc) => (uc.use_case === useCase ? patch(uc) : uc)),
  };
}

async function beginOptimistic(
  queryClient: QueryClient,
  useCase: string,
  patch: (uc: LLMUseCase) => LLMUseCase,
): Promise<MutationContext> {
  await queryClient.cancelQueries({ queryKey: LLM_SETTINGS_KEY });
  const previous = queryClient.getQueryData<LLMSettingsResponse>(LLM_SETTINGS_KEY);
  if (previous) {
    queryClient.setQueryData<LLMSettingsResponse>(
      LLM_SETTINGS_KEY,
      patchUseCase(previous, useCase, patch),
    );
  }
  return { previous };
}

// ── Mutations ─────────────────────────────────────────────────────

/**
 * PUT an override for one use case. Optimistic: the row flips to the new
 * config (override + effective) immediately; rolled back on error. The
 * global MutationCache onError in App.tsx raises the toast.
 */
export function useSetLLMOverride() {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, { useCase: string; config: LLMConfig }, MutationContext>({
    mutationFn: async ({ useCase, config }) => {
      await api.put(`/settings/llm/${useCase}`, config);
    },
    onMutate: ({ useCase, config }) =>
      beginOptimistic(queryClient, useCase, (uc) => ({
        ...uc,
        override: config,
        effective: config,
      })),
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(LLM_SETTINGS_KEY, context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: LLM_SETTINGS_KEY });
      invalidateEstimateDebounced(queryClient);
    },
  });
}

/**
 * DELETE an override → the use case reverts to its registry default.
 * Optimistic: override clears and effective snaps back to default.
 */
export function useResetLLMOverride() {
  const queryClient = useQueryClient();
  return useMutation<void, unknown, { useCase: string }, MutationContext>({
    mutationFn: async ({ useCase }) => {
      await api.delete(`/settings/llm/${useCase}`);
    },
    onMutate: ({ useCase }) =>
      beginOptimistic(queryClient, useCase, (uc) => ({
        ...uc,
        override: null,
        effective: uc.default,
      })),
    onError: (_error, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(LLM_SETTINGS_KEY, context.previous);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: LLM_SETTINGS_KEY });
      invalidateEstimateDebounced(queryClient);
    },
  });
}
