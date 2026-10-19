import api from './api';

/** `OnboardingState` (S-8.10.1): the wizard's progress, kept on the user row. */
export interface OnboardingState {
  step: 1 | 2 | 3;
  choices: { channels: string[]; first_job_id: string | null };
  dismissed: boolean;
  started_at: string | null;
  completed_at: string | null;
  dismissed_at: string | null;
}

export interface OnboardingFirstJob {
  id: string;
  job_type: string;
  status: string;
  has_report: boolean;
}

/** `GET /auth/me/onboarding`. Milestones are derived on read from runs and the audit log. */
export interface Onboarding {
  onboarded_at: string | null;
  state: OnboardingState;
  started: boolean;
  milestones: { jobs: number; first_job: OnboardingFirstJob | null; report_opened: boolean };
  /** Whether `/` sends this account to `/welcome`. */
  should_onboard: boolean;
}

export interface OnboardingPatch {
  step?: 1 | 2 | 3;
  channels?: string[];
  first_job_id?: string;
  completed?: boolean;
  dismissed?: boolean;
}

/** The server caps the channel list at five (`onboarding_service.MAX_CHANNELS`). */
export const MAX_ONBOARDING_CHANNELS = 5;

/** Videos in the first run: small on purpose, so the report arrives in minutes. */
export const FIRST_RUN_VIDEOS = 5;

export const onboardingApi = {
  get: () => api.get<Onboarding>('/auth/me/onboarding').then(r => r.data),
  patch: (body: OnboardingPatch) => api.patch<Onboarding>('/auth/me/onboarding', body).then(r => r.data),
};
