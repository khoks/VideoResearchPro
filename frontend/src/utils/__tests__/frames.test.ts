/** S-1.18.2: which frame a cited moment refers to. */
import { describe, expect, it } from 'vitest';
import { nearestFrame, usableFrames, type VideoFrame } from '../frames';

const frame = (ts: number, extra: Partial<VideoFrame> = {}): VideoFrame => ({
  frame_id: `f${ts}`,
  timestamp_seconds: ts,
  timestamp_display: `${Math.floor(ts / 60)}:${String(ts % 60).padStart(2, '0')}`,
  description: `at ${ts}`,
  informative: true,
  status: 'described',
  width: 640,
  height: 360,
  has_image: true,
  ...extra,
});

describe('usableFrames', () => {
  it('keeps described, informative frames whose image exists', () => {
    const frames = [
      frame(10),
      frame(20, { status: 'captured' }),
      frame(30, { informative: false }),
      frame(40, { has_image: false }),
      frame(50, { informative: null }),
    ];
    expect(usableFrames(frames).map((f) => f.timestamp_seconds)).toEqual([10, 50]);
  });
});

describe('nearestFrame', () => {
  const frames = [frame(100), frame(200), frame(330)];

  it('takes the closest frame inside the window', () => {
    expect(nearestFrame(frames, 190)?.timestamp_seconds).toBe(200);
    expect(nearestFrame(frames, 105)?.timestamp_seconds).toBe(100);
  });

  it('reaches up to two minutes after a link, since links point at a chunk start', () => {
    expect(nearestFrame([frame(320)], 200)?.timestamp_seconds).toBe(320);
    expect(nearestFrame([frame(321)], 200)).toBeNull();
  });

  it('reaches only a little before a link', () => {
    expect(nearestFrame([frame(180)], 200)?.timestamp_seconds).toBe(180);
    expect(nearestFrame([frame(179)], 200)).toBeNull();
  });

  it('returns null without a timestamp or usable frames', () => {
    expect(nearestFrame(frames, null)).toBeNull();
    expect(nearestFrame([frame(200, { has_image: false })], 200)).toBeNull();
  });
});
