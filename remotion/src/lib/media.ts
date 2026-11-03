import {staticFile} from 'remotion';

// render.py stages local files into the public dir and passes relative names; URLs pass through.
export const src = (value: string) => (/^(https?:|data:|blob:)/.test(value) ? value : staticFile(value));

export const isVideo = (value: string) => /\.(mp4|mov|webm|m4v|mkv)$/i.test(value);

export const frames = (seconds: number, fps: number) => Math.max(1, Math.round(seconds * fps));

/** Overlap of two clips in frames; 0 for a cut (frames() would round a 0 s overlap up to 1 frame). */
export const transitionFrames = (t: {type?: string; seconds?: number} | null | undefined, fps: number) => {
  const seconds = !t || t.type === 'cut' ? 0 : t.seconds ?? 0.35;
  return seconds > 0 ? frames(seconds, fps) : 0;
};
