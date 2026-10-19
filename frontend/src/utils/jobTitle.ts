import type { Job } from '../types/job';

/** The title a run is known by across list rows, shelf rows and chips. */
export function jobDisplayTitle(job: Pick<Job, 'job_type' | 'topic' | 'channel_list'>): string {
  if (job.job_type === 'topic') return job.topic ?? 'Untitled topic';
  const channels = job.channel_list;
  if (job.job_type === 'subscription') {
    const list = channels && channels.length > 0 ? channels.join(', ') : '';
    return `Subscription: ${list}`;
  }
  if (channels && channels.length > 0) return channels.join(', ');
  return 'Channel Collection';
}

export function jobTypeLabel(type: Job['job_type']): string {
  if (type === 'topic') return 'Topic';
  if (type === 'channel') return 'Channel';
  return 'Subscription';
}
