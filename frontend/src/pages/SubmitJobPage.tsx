import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCreateJob } from '../hooks/useJobs';
import type { JobCreate, JobType } from '../types/job';

export function SubmitJobPage() {
  const navigate = useNavigate();
  const createJob = useCreateJob();
  const [jobType, setJobType] = useState<JobType>('topic');
  const [topic, setTopic] = useState('');
  const [searchInstructions, setSearchInstructions] = useState('');
  const [numVideos, setNumVideos] = useState(10);
  const [minDuration, setMinDuration] = useState('');
  const [maxDuration, setMaxDuration] = useState('');
  const [channelFilters, setChannelFilters] = useState('');
  const [channelList, setChannelList] = useState('');
  const [videosPerChannel, setVideosPerChannel] = useState(10);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const data: JobCreate = { job_type: jobType, num_videos: numVideos };

    if (jobType === 'topic') {
      data.topic = topic;
      data.search_instructions = searchInstructions || undefined;
      if (minDuration) data.min_duration_minutes = parseInt(minDuration);
      if (maxDuration) data.max_duration_minutes = parseInt(maxDuration);
      if (channelFilters) data.channel_type_filters = channelFilters.split(',').map(s => s.trim());
    } else {
      data.channel_list = channelList.split('\n').map(s => s.trim()).filter(Boolean);
      data.videos_per_channel = videosPerChannel;
    }

    const job = await createJob.mutateAsync(data);
    navigate(`/jobs/${job.id}`);
  };

  return (
    <div style={{ maxWidth: 700, margin: '0 auto' }}>
      <h2 style={{ marginBottom: '1.5rem', color: '#1e293b' }}>Submit New Research Job</h2>

      <div style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
        <TypeToggle active={jobType === 'topic'} onClick={() => setJobType('topic')}>
          Topic Research
        </TypeToggle>
        <TypeToggle active={jobType === 'channel'} onClick={() => setJobType('channel')}>
          Channel Scrape
        </TypeToggle>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
        {jobType === 'topic' ? (
          <>
            <Field label="Research Topic *">
              <input value={topic} onChange={(e) => setTopic(e.target.value)}
                     placeholder="e.g. Quantum Computing breakthroughs 2025" required />
            </Field>
            <Field label="Search Instructions (optional)">
              <textarea value={searchInstructions} onChange={(e) => setSearchInstructions(e.target.value)}
                        placeholder="e.g. Focus on academic channels, prefer recent uploads..." rows={3} />
            </Field>
            <Field label="Number of Videos">
              <input type="number" value={numVideos} onChange={(e) => setNumVideos(parseInt(e.target.value))}
                     min={1} max={100} />
            </Field>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <Field label="Min Duration (minutes)">
                <input type="number" value={minDuration} onChange={(e) => setMinDuration(e.target.value)}
                       placeholder="Any" min={1} />
              </Field>
              <Field label="Max Duration (minutes)">
                <input type="number" value={maxDuration} onChange={(e) => setMaxDuration(e.target.value)}
                       placeholder="Any" min={1} />
              </Field>
            </div>
            <Field label="Channel Type Filters (comma-separated, optional)">
              <input value={channelFilters} onChange={(e) => setChannelFilters(e.target.value)}
                     placeholder="e.g. educational, academic, news" />
            </Field>
          </>
        ) : (
          <>
            <Field label="YouTube Channels (one per line) *">
              <textarea value={channelList} onChange={(e) => setChannelList(e.target.value)}
                        placeholder={"@3blue1brown\n@Veritasium\nhttps://youtube.com/@kurzgesagt"}
                        rows={5} required />
            </Field>
            <Field label="Videos per Channel">
              <input type="number" value={videosPerChannel}
                     onChange={(e) => setVideosPerChannel(parseInt(e.target.value))}
                     min={1} max={50} />
            </Field>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <Field label="Min Duration (minutes)">
                <input type="number" value={minDuration} onChange={(e) => setMinDuration(e.target.value)}
                       placeholder="Any" min={1} />
              </Field>
              <Field label="Max Duration (minutes)">
                <input type="number" value={maxDuration} onChange={(e) => setMaxDuration(e.target.value)}
                       placeholder="Any" min={1} />
              </Field>
            </div>
          </>
        )}

        <button type="submit" disabled={createJob.isPending} style={{
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          color: '#fff', border: 'none', padding: '0.8rem 2rem', borderRadius: 8,
          fontSize: '1rem', fontWeight: 600, cursor: 'pointer', marginTop: '0.5rem',
          opacity: createJob.isPending ? 0.7 : 1,
        }}>
          {createJob.isPending ? 'Submitting...' : 'Submit Job'}
        </button>

        {createJob.isError && (
          <p style={{ color: '#ef4444' }}>
            Error: {(createJob.error as Error).message}
          </p>
        )}
      </form>
    </div>
  );
}

function TypeToggle({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode;
}) {
  return (
    <button type="button" onClick={onClick} style={{
      padding: '0.6rem 1.5rem', borderRadius: 8, border: '2px solid',
      borderColor: active ? '#667eea' : '#e2e8f0',
      background: active ? '#667eea' : '#fff',
      color: active ? '#fff' : '#64748b',
      fontWeight: 600, cursor: 'pointer', transition: 'all 0.2s',
    }}>
      {children}
    </button>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem', flex: 1 }}>
      <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#475569' }}>{label}</span>
      {children}
    </label>
  );
}
