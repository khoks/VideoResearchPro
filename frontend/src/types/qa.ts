export interface Reference {
  video_url: string;
  video_title: string;
  channel_name: string;
  timestamp_seconds: number;
  timestamp_display: string;
  youtube_link: string;
}

export interface QAExchange {
  id: string;
  question: string;
  answer: string;
  references: Reference[];
  created_at: string;
}

export interface QARequest {
  question: string;
  context?: string;
}

export interface ClarifyRequest {
  question: string;
}

export interface ClarifyResponse {
  interpretation: string;
  clarifications: string[];
}
